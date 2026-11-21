// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {CategoricalMarketEngine} from "../src/CategoricalMarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockCategoricalOracle} from "../src/mocks/MockCategoricalOracle.sol";

/// @notice Drives random, interleaved sequences of the four engine actions
///         (create / position / resolve / claim) across many N-outcome markets
///         and a fixed set of actors. Unlike the binary handler, each market has
///         a random outcome count and the resolve step reaches all four
///         settlement paths — a funded winner (Resolved + fee), a winning outcome
///         with no stake (no-winner void), an out-of-range index (void), and the
///         invalid sentinel (void) — so solvency is asserted across an arbitrary
///         history that includes every void the dynamic pools array can hit.
contract CategoricalMarketEngineHandler is MiniTest {
    CategoricalMarketEngine public immutable engine;
    MockERC20 public immutable collateral;
    MockCategoricalOracle public immutable oracle;
    Treasury public immutable treasury;

    address[4] public actors = [address(0xA1), address(0xA2), address(0xB1), address(0xB2)];

    bytes32[] public marketIds;
    mapping(bytes32 => uint64) public closeAtOf;
    mapping(bytes32 => uint8) public outcomeCountOf;
    mapping(bytes32 => bool) public settled;

    // --- ghost accounting (read by the invariants) ---
    uint256 public g_totalDeposited;
    uint256 public g_totalPaidOut;
    uint256 public g_totalFees;

    uint256 constant MIN_STAKE = 1;
    uint256 constant MAX_STAKE = 1e24;
    uint8 constant MIN_OUTCOMES = 2;
    uint8 constant MAX_OUTCOMES = 6; // small N keeps the pools loops cheap across many markets

    constructor(
        CategoricalMarketEngine _engine,
        MockERC20 _collateral,
        MockCategoricalOracle _oracle,
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

    /// Open a fresh N-outcome market. Unique question hash per call avoids an id
    /// collision; N is random in [2, 6].
    function createMarket(uint256 seed, uint32 window) external {
        uint64 closeAt = uint64(block.timestamp + _bound(window, 1 hours, 7 days));
        bytes32 qhash = keccak256(abi.encode(seed, marketIds.length, block.timestamp));
        uint8 n = uint8(_bound(seed, MIN_OUTCOMES, MAX_OUTCOMES));
        bytes32 id = engine.createMarket(qhash, closeAt, n, "");
        marketIds.push(id);
        closeAtOf[id] = closeAt;
        outcomeCountOf[id] = n;
    }

    /// An actor stakes on one outcome of an open market (within its window).
    function takePosition(uint256 mSeed, uint256 aSeed, uint8 oSeed, uint96 amt) external {
        if (marketIds.length == 0) return;
        bytes32 id = marketIds[_bound(mSeed, 0, marketIds.length - 1)];
        if (settled[id] || block.timestamp >= closeAtOf[id]) return;

        address who = actors[_bound(aSeed, 0, 3)];
        uint8 outcome = uint8(_bound(oSeed, 0, outcomeCountOf[id] - 1));
        uint256 amount = _bound(amt, MIN_STAKE, MAX_STAKE);

        collateral.mint(who, amount);
        vm.startPrank(who);
        collateral.approve(address(engine), amount);
        engine.takePosition(id, outcome, amount);
        vm.stopPrank();

        g_totalDeposited += amount;
    }

    /// Warp past a market's close, choose a winning outcome, and resolve it (zero
    /// challenge window -> atomic settlement). The chosen index deliberately ranges
    /// over valid outcomes, the out-of-range value N, and (sometimes) the invalid
    /// sentinel, so the void paths are exercised as often as the funded-winner one.
    /// The fee handed to the treasury is captured as a balance delta, robust to
    /// whichever settlement path fired (voids skim nothing).
    function resolveMarket(uint256 mSeed, uint16 oSeed) external {
        if (marketIds.length == 0) return;
        bytes32 id = marketIds[_bound(mSeed, 0, marketIds.length - 1)];
        if (settled[id]) return;

        uint64 target = closeAtOf[id] + 1;
        if (block.timestamp < target) vm.warp(target);

        if (oSeed % 5 == 0) {
            oracle.setInvalid(id); // sentinel -> void
        } else {
            // [0, N-1] are real outcomes (funded -> Resolved, empty -> no-winner void);
            // N itself is out of range -> void.
            uint8 outcome = uint8(_bound(oSeed, 0, outcomeCountOf[id]));
            oracle.set(id, outcome);
        }

        uint256 feeBefore = collateral.balanceOf(address(treasury));
        engine.resolve(id);
        g_totalFees += collateral.balanceOf(address(treasury)) - feeBefore;

        settled[id] = true;
    }

    /// An actor attempts to claim. Losers / non-participants / double-claims and
    /// unresolved markets revert inside the engine; the try/catch keeps the
    /// sequence productive and only credits the ghost total on a real payout
    /// (a winner's share on a Resolved market, or a principal refund on a void).
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

/// @notice Stateful invariant suite for the categorical engine. Where
///         `CategoricalMarketEngineFuzz` proves one settlement correct for random
///         stakes and outcome counts, these prove the engine stays solvent and the
///         books balance across an unbounded, randomly interleaved history of many
///         N-outcome markets, actors, and settlement outcomes (winners and all
///         three voids) — what single-settlement fuzzing can't reach.
contract CategoricalMarketEngineInvariantTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    MockCategoricalOracle oracle;
    CategoricalMarketEngine engine;
    CategoricalMarketEngineHandler handler;

    address admin = address(0xA11CE);
    bytes32 constant OPS = keccak256("OPERATIONS");

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(admin);
        oracle = new MockCategoricalOracle();
        engine = new CategoricalMarketEngine(address(collateral), address(oracle), address(treasury), admin);

        handler = new CategoricalMarketEngineHandler(engine, collateral, oracle, treasury);
        vm.prank(admin);
        engine.setRelayer(address(handler), true);
    }

    /// Only the handler's actions are fuzzed (forge reads this getter).
    function targetContracts() public view returns (address[] memory addrs) {
        addrs = new address[](1);
        addrs[0] = address(handler);
    }

    /// Conservation / solvency: every token that entered the engine is still held,
    /// was paid out as a claim (winner share or void refund), or was skimmed as a
    /// fee. Nothing leaks across any interleaving of N-outcome markets.
    function invariant_valueIsConserved() public view {
        assertEq(
            collateral.balanceOf(address(engine)) + handler.g_totalPaidOut() + handler.g_totalFees(),
            handler.g_totalDeposited(),
            "engine balance + paid + fees == deposited"
        );
    }

    /// The treasury holds exactly the fees skimmed (only from funded winners;
    /// voids skim nothing), and the OPERATIONS bucket accounts for every one.
    function invariant_treasuryHoldsExactlyFees() public view {
        assertEq(collateral.balanceOf(address(treasury)), handler.g_totalFees(), "treasury == fees");
        assertEq(treasury.reserves(OPS, address(collateral)), handler.g_totalFees(), "bucket == fees");
    }

    /// Fees can never exceed what was ever deposited.
    function invariant_feesWithinDeposits() public view {
        assertLe(handler.g_totalFees(), handler.g_totalDeposited(), "fees <= deposited");
    }
}
