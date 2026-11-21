// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {ScalarMarketEngine} from "../src/ScalarMarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockScalarOracle} from "../src/mocks/MockScalarOracle.sol";

/// @notice Drives random, interleaved sequences of the four engine actions
///         (create / position / resolve / claim) across many range markets and a
///         fixed set of actors. Each market gets a random band (which may be
///         negative), actors stake LONG or SHORT at random, and the resolve step
///         sets an oracle value spanning below / inside / above the band so the
///         clamp reaches every split — SHORT-takes-all, a mid-band share, and
///         LONG-takes-all — while markets that drew stake on only one side hit
///         the structural one-sided void. Solvency is asserted after an arbitrary
///         history that exercises the continuous payout and the void alike.
contract ScalarMarketEngineHandler is MiniTest {
    ScalarMarketEngine public immutable engine;
    MockERC20 public immutable collateral;
    MockScalarOracle public immutable oracle;
    Treasury public immutable treasury;

    address[4] public actors = [address(0xA1), address(0xA2), address(0xB1), address(0xB2)];

    bytes32[] public marketIds;
    mapping(bytes32 => uint64) public closeAtOf;
    mapping(bytes32 => int256) public lowerOf;
    mapping(bytes32 => int256) public upperOf;
    mapping(bytes32 => bool) public settled;

    // --- ghost accounting (read by the invariants) ---
    uint256 public g_totalDeposited;
    uint256 public g_totalPaidOut;
    uint256 public g_totalFees;

    uint256 constant MIN_STAKE = 1;
    uint256 constant MAX_STAKE = 1e24;

    constructor(
        ScalarMarketEngine _engine,
        MockERC20 _collateral,
        MockScalarOracle _oracle,
        Treasury _treasury
    ) {
        engine = _engine;
        collateral = _collateral;
        oracle = _oracle;
        treasury = _treasury;
    }

    function marketCount() external view returns (uint256) {
        return marketIds.length;
    }

    /// Open a fresh range market. Unique question hash per call avoids an id
    /// collision; the band is random and may straddle zero.
    function createMarket(uint256 seed, uint32 window, uint32 widthSeed) external {
        uint64 closeAt = uint64(block.timestamp + _bound(window, 1 hours, 7 days));
        bytes32 qhash = keccak256(abi.encode(seed, marketIds.length, block.timestamp));
        int256 lower = int256(_bound(seed, 0, 2000)) - 1000; // [-1000, 1000]
        int256 upper = lower + int256(_bound(widthSeed, 1, 1_000_000)); // width in [1, 1e6]
        bytes32 id = engine.createMarket(qhash, closeAt, lower, upper, "");
        marketIds.push(id);
        closeAtOf[id] = closeAt;
        lowerOf[id] = lower;
        upperOf[id] = upper;
    }

    /// An actor stakes LONG or SHORT on an open market (within its window).
    function takePosition(uint256 mSeed, uint256 aSeed, bool long, uint96 amt) external {
        if (marketIds.length == 0) return;
        bytes32 id = marketIds[_bound(mSeed, 0, marketIds.length - 1)];
        if (settled[id] || block.timestamp >= closeAtOf[id]) return;

        address who = actors[_bound(aSeed, 0, 3)];
        uint256 amount = _bound(amt, MIN_STAKE, MAX_STAKE);
        ScalarMarketEngine.Side side = long ? ScalarMarketEngine.Side.Long : ScalarMarketEngine.Side.Short;

        collateral.mint(who, amount);
        vm.startPrank(who);
        collateral.approve(address(engine), amount);
        engine.takePosition(id, side, amount);
        vm.stopPrank();

        g_totalDeposited += amount;
    }

    /// Warp past a market's close, set an oracle value spanning [lo - span, hi + span]
    /// (so the clamp reaches SHORT-all, a mid-band split, and LONG-all), and resolve
    /// (zero challenge window -> atomic settlement; a one-sided book voids). The fee
    /// handed to the treasury is captured as a balance delta, robust to whether the
    /// market settled or voided (voids skim nothing).
    function resolveMarket(uint256 mSeed, uint256 vSeed) external {
        if (marketIds.length == 0) return;
        bytes32 id = marketIds[_bound(mSeed, 0, marketIds.length - 1)];
        if (settled[id]) return;

        uint64 target = closeAtOf[id] + 1;
        if (block.timestamp < target) vm.warp(target);

        int256 lo = lowerOf[id];
        int256 hi = upperOf[id];
        uint256 span = uint256(hi - lo);
        int256 value = lo - int256(span) + int256(_bound(vSeed, 0, 3 * span));
        oracle.set(id, value);

        uint256 feeBefore = collateral.balanceOf(address(treasury));
        engine.resolve(id);
        g_totalFees += collateral.balanceOf(address(treasury)) - feeBefore;

        settled[id] = true;
    }

    /// An actor attempts to claim. Non-participants / double-claims and unresolved
    /// markets revert inside the engine; the try/catch keeps the sequence
    /// productive. A payout can legitimately be 0 (a wholly-losing stake), which the
    /// engine still records as claimed and the ghost total absorbs harmlessly.
    function claim(uint256 mSeed, uint256 aSeed) external {
        if (marketIds.length == 0) return;
        bytes32 id = marketIds[_bound(mSeed, 0, marketIds.length - 1)];
        address who = actors[_bound(aSeed, 0, 3)];

        vm.prank(who);
        try engine.claim(id) returns (uint256 payout) {
            g_totalPaidOut += payout;
        } catch {}
    }
}

/// @notice Stateful invariant suite for the scalar engine. Where
///         `ScalarMarketEngineFuzz` proves one settlement correct for random
///         stakes and values, these prove the engine stays solvent and the books
///         balance across an unbounded, randomly interleaved history of many
///         range markets, actors, and settlement outcomes (clamped either way, a
///         mid-band split, and the one-sided void). Floor-division dust stays in
///         the engine, so conservation holds exactly.
contract ScalarMarketEngineInvariantTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    MockScalarOracle oracle;
    ScalarMarketEngine engine;
    ScalarMarketEngineHandler handler;

    address admin = address(0xA11CE);
    bytes32 constant OPS = keccak256("OPERATIONS");

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(admin);
        oracle = new MockScalarOracle();
        engine = new ScalarMarketEngine(address(collateral), address(oracle), address(treasury), admin);

        handler = new ScalarMarketEngineHandler(engine, collateral, oracle, treasury);
        vm.prank(admin);
        engine.setRelayer(address(handler), true);
    }

    /// Only the handler's actions are fuzzed (forge reads this getter).
    function targetContracts() public view returns (address[] memory addrs) {
        addrs = new address[](1);
        addrs[0] = address(handler);
    }

    /// Conservation / solvency: every token that entered the engine is still held
    /// (including floor-division dust), was paid out as a claim (a side's share or a
    /// void refund), or was skimmed as a fee. Nothing leaks across any interleaving.
    function invariant_valueIsConserved() public view {
        assertEq(
            collateral.balanceOf(address(engine)) + handler.g_totalPaidOut() + handler.g_totalFees(),
            handler.g_totalDeposited(),
            "engine balance + paid + fees == deposited"
        );
    }

    /// The treasury holds exactly the fees skimmed (only from settled markets;
    /// one-sided voids skim nothing), and the OPERATIONS bucket accounts for every one.
    function invariant_treasuryHoldsExactlyFees() public view {
        assertEq(collateral.balanceOf(address(treasury)), handler.g_totalFees(), "treasury == fees");
        assertEq(treasury.reserves(OPS, address(collateral)), handler.g_totalFees(), "bucket == fees");
    }

    /// Fees can never exceed what was ever deposited.
    function invariant_feesWithinDeposits() public view {
        assertLe(handler.g_totalFees(), handler.g_totalDeposited(), "fees <= deposited");
    }
}
