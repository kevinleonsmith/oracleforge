// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {MarketEngine} from "../src/MarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockOracleAdapter} from "../src/mocks/MockOracleAdapter.sol";
import {IMarketEngine} from "../src/interfaces/IMarketEngine.sol";
import {IOracleAdapter} from "../src/interfaces/IOracleAdapter.sol";

/// @notice Drives random, interleaved sequences of the four engine actions
///         (create / position / resolve / claim) across many markets and a
///         fixed set of actors. It keeps ghost totals of every token that has
///         entered the engine, been paid out, or been skimmed as a fee, so the
///         test can assert global solvency after an *arbitrary* history — the
///         thing single-settlement fuzzing can't reach.
contract MarketEngineHandler is MiniTest {
    MarketEngine public immutable engine;
    MockERC20 public immutable collateral;
    MockOracleAdapter public immutable oracle;
    Treasury public immutable treasury;

    address[4] public actors = [address(0xA1), address(0xA2), address(0xB1), address(0xB2)];

    bytes32[] public marketIds;
    mapping(bytes32 => uint64) public closeAtOf;
    mapping(bytes32 => bool) public settled;

    // --- ghost accounting (read by the invariants) ---
    uint256 public g_totalDeposited;
    uint256 public g_totalPaidOut;
    uint256 public g_totalFees;

    uint256 constant MIN_STAKE = 1;
    uint256 constant MAX_STAKE = 1e24;

    constructor(MarketEngine _engine, MockERC20 _collateral, MockOracleAdapter _oracle, Treasury _treasury) {
        engine = _engine;
        collateral = _collateral;
        oracle = _oracle;
        treasury = _treasury;
    }

    function _max(uint256 a, uint256 b) private pure returns (uint256) {
        return a >= b ? a : b;
    }

    function marketCount() external view returns (uint256) {
        return marketIds.length;
    }

    /// Open a fresh market. Unique question hash per call avoids an id collision.
    function createMarket(uint256 seed, uint32 window) external {
        uint64 closeAt = uint64(block.timestamp + _bound(window, 1 hours, 7 days));
        bytes32 qhash = keccak256(abi.encode(seed, marketIds.length, block.timestamp));
        bytes32 id = engine.createMarket(qhash, closeAt, uint16(_bound(seed, 0, 10_000)), "");
        marketIds.push(id);
        closeAtOf[id] = closeAt;
    }

    /// An actor stakes on one side of an open market (within its window).
    function takePosition(uint256 mSeed, uint256 aSeed, bool yes, uint96 amt) external {
        if (marketIds.length == 0) return;
        bytes32 id = marketIds[_bound(mSeed, 0, marketIds.length - 1)];
        if (settled[id] || block.timestamp >= closeAtOf[id]) return;

        address who = actors[_bound(aSeed, 0, 3)];
        uint256 amount = _bound(amt, MIN_STAKE, MAX_STAKE);
        IMarketEngine.Side side = yes ? IMarketEngine.Side.Yes : IMarketEngine.Side.No;

        collateral.mint(who, amount);
        vm.startPrank(who);
        collateral.approve(address(engine), amount);
        engine.takePosition(id, side, amount);
        vm.stopPrank();

        g_totalDeposited += amount;
    }

    /// Warp past a market's close, pick an outcome, and resolve it. The fee the
    /// engine hands the treasury is captured as a balance delta (robust to the
    /// exact fee math).
    function resolveMarket(uint256 mSeed, uint8 oSeed) external {
        if (marketIds.length == 0) return;
        bytes32 id = marketIds[_bound(mSeed, 0, marketIds.length - 1)];
        if (settled[id]) return;

        uint64 target = closeAtOf[id] + 1;
        if (block.timestamp < target) vm.warp(target);

        // 1 = Yes, 2 = No, 3 = Invalid (never Pending)
        oracle.setOutcome(id, IOracleAdapter.Outcome(uint8(_bound(oSeed, 1, 3))));

        uint256 feeBefore = collateral.balanceOf(address(treasury));
        engine.resolve(id);
        g_totalFees += collateral.balanceOf(address(treasury)) - feeBefore;

        settled[id] = true;
    }

    /// An actor attempts to claim. Losers / non-participants / double-claims
    /// revert inside the engine; the try/catch keeps the sequence productive and
    /// only credits the ghost total on a real payout.
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

/// @notice Stateful invariant suite. Where `MarketEngineFuzz` proves one
///         settlement correct for random stakes, these prove the engine stays
///         solvent and the books balance across an unbounded, randomly
///         interleaved history of many markets and actors.
contract MarketEngineInvariantTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    MockOracleAdapter oracle;
    MarketEngine engine;
    MarketEngineHandler handler;

    address admin = address(0xA11CE);
    bytes32 constant OPS = keccak256("OPERATIONS");

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(admin);
        oracle = new MockOracleAdapter();
        engine = new MarketEngine(address(collateral), address(oracle), address(treasury), admin);

        handler = new MarketEngineHandler(engine, collateral, oracle, treasury);
        vm.prank(admin);
        engine.setRelayer(address(handler), true);
    }

    /// Only the handler's actions are fuzzed (forge reads this getter).
    function targetContracts() public view returns (address[] memory addrs) {
        addrs = new address[](1);
        addrs[0] = address(handler);
    }

    /// Conservation / solvency: every token that entered the engine is still
    /// held, was paid out as a claim, or was skimmed as a fee. Nothing leaks.
    function invariant_valueIsConserved() public view {
        assertEq(
            collateral.balanceOf(address(engine)) + handler.g_totalPaidOut() + handler.g_totalFees(),
            handler.g_totalDeposited(),
            "engine balance + paid + fees == deposited"
        );
    }

    /// The treasury holds exactly the fees skimmed, and the OPERATIONS bucket
    /// accounts for every one of them.
    function invariant_treasuryHoldsExactlyFees() public view {
        assertEq(collateral.balanceOf(address(treasury)), handler.g_totalFees(), "treasury == fees");
        assertEq(treasury.reserves(OPS, address(collateral)), handler.g_totalFees(), "bucket == fees");
    }

    /// Fees can never exceed what was ever deposited.
    function invariant_feesWithinDeposits() public view {
        assertLe(handler.g_totalFees(), handler.g_totalDeposited(), "fees <= deposited");
    }
}
