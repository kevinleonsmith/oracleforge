// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {ScalarMarketEngine} from "../src/ScalarMarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockScalarOracle} from "../src/mocks/MockScalarOracle.sol";

/// @notice Drives the scalar engine's optimistic-resolution path under load: a
///         live challenge window and dispute bond, with randomly-interleaved
///         propose / dispute / arbitrate / finalize / claim across many range
///         markets and actors, and an adversarial `churnBond` action rewriting the
///         global disputeBond while challenges are open. A one-sided book voids at
///         resolve (bypassing the window), so those markets never reach a dispute —
///         the handler routes by live status. Bonds are first-class ghost state, so
///         the suite can assert solvency once bonds flow through the engine.
contract ScalarMarketEngineDisputeHandler is MiniTest {
    ScalarMarketEngine public immutable engine;
    MockERC20 public immutable collateral;
    MockScalarOracle public immutable oracle;
    Treasury public immutable treasury;
    address public immutable admin;

    address[4] public actors = [address(0xA1), address(0xA2), address(0xB1), address(0xB2)];

    bytes32[] public marketIds;
    mapping(bytes32 => uint64) public closeAtOf;
    mapping(bytes32 => int256) public lowerOf;
    mapping(bytes32 => int256) public upperOf;

    // --- ghost accounting (read by the invariants) ---
    uint256 public g_totalDeposited; // stakes pulled in
    uint256 public g_totalBondsPosted; // bonds pulled in by dispute()
    uint256 public g_totalPaidOut; // claims + refunded bonds paid back out to users
    uint256 public g_openBondTotal; // bonds currently locked in undecided disputes

    uint256 constant MIN_STAKE = 1;
    uint256 constant MAX_STAKE = 1e24;
    uint256 constant MAX_BOND = 1e24;

    constructor(
        ScalarMarketEngine _engine,
        MockERC20 _collateral,
        MockScalarOracle _oracle,
        Treasury _treasury,
        address _admin
    ) {
        engine = _engine;
        collateral = _collateral;
        oracle = _oracle;
        treasury = _treasury;
        admin = _admin;
    }

    function marketCount() external view returns (uint256) {
        return marketIds.length;
    }

    function _pick(uint256 mSeed) internal view returns (bytes32) {
        return marketIds[_bound(mSeed, 0, marketIds.length - 1)];
    }

    function _status(bytes32 id) internal view returns (ScalarMarketEngine.Status) {
        return engine.getMarket(id).status;
    }

    function _windowEnd(bytes32 id) internal view returns (uint256) {
        return uint256(engine.proposedAt(id)) + uint256(engine.challengeWindow());
    }

    /// Open a fresh range market with a short close and a band that may straddle zero.
    function createMarket(uint256 seed, uint32 window, uint32 widthSeed) external {
        uint64 closeAt = uint64(block.timestamp + _bound(window, 1 hours, 2 hours));
        bytes32 qhash = keccak256(abi.encode(seed, marketIds.length, block.timestamp));
        int256 lower = int256(_bound(seed, 0, 2000)) - 1000;
        int256 upper = lower + int256(_bound(widthSeed, 1, 1_000_000));
        bytes32 id = engine.createMarket(qhash, closeAt, lower, upper, "");
        marketIds.push(id);
        closeAtOf[id] = closeAt;
        lowerOf[id] = lower;
        upperOf[id] = upper;
    }

    /// An actor stakes LONG or SHORT on an open market (within its window).
    function takePosition(uint256 mSeed, uint256 aSeed, bool long, uint96 amt) external {
        if (marketIds.length == 0) return;
        bytes32 id = _pick(mSeed);
        if (_status(id) != ScalarMarketEngine.Status.Open || block.timestamp >= closeAtOf[id]) return;

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

    /// Warp past close, set an oracle value, and resolve — which (window > 0)
    /// *proposes* the clamped value (status Closed), unless the book is one-sided,
    /// which voids immediately (status Invalid, bypassing the window).
    function proposeResolve(uint256 mSeed, uint256 vSeed) external {
        if (marketIds.length == 0) return;
        bytes32 id = _pick(mSeed);
        if (_status(id) != ScalarMarketEngine.Status.Open) return;

        uint64 target = closeAtOf[id] + 1;
        if (block.timestamp < target) vm.warp(target);
        uint256 span = uint256(upperOf[id] - lowerOf[id]);
        int256 value = lowerOf[id] - int256(span) + int256(_bound(vSeed, 0, 3 * span));
        oracle.set(id, value);
        engine.resolve(id);
    }

    /// An actor challenges a proposed value within its window, posting the current
    /// global bond (which the engine snapshots). Records the exact amount posted.
    function disputeMarket(uint256 mSeed, uint256 aSeed) external {
        if (marketIds.length == 0) return;
        bytes32 id = _pick(mSeed);
        if (_status(id) != ScalarMarketEngine.Status.Closed) return;
        if (engine.challengerOf(id) != address(0)) return;
        uint256 bond = engine.disputeBond();
        if (bond == 0 || block.timestamp >= _windowEnd(id)) return;

        address who = actors[_bound(aSeed, 0, 3)];
        collateral.mint(who, bond);
        vm.startPrank(who);
        collateral.approve(address(engine), bond);
        engine.dispute(id);
        vm.stopPrank();

        g_totalBondsPosted += bond;
        g_openBondTotal += bond;
    }

    /// The admin arbitrates an open dispute with an authoritative value (the engine
    /// clamps it). The bond is read from the snapshot before arbitration zeroes it:
    /// an upheld challenge refunds it, a rejected one forfeits it to the treasury.
    function arbitrateMarket(uint256 mSeed, uint256 vSeed, bool upheld) external {
        if (marketIds.length == 0) return;
        bytes32 id = _pick(mSeed);
        if (engine.challengerOf(id) == address(0)) return;

        uint256 bond = engine.bondOf(id);
        // any int in the band; the engine clamps regardless
        int256 finalValue = lowerOf[id] + int256(_bound(vSeed, 0, uint256(upperOf[id] - lowerOf[id])));
        vm.prank(admin);
        engine.arbitrate(id, finalValue, upheld);

        g_openBondTotal -= bond;
        if (upheld) g_totalPaidOut += bond;
    }

    /// Finalize a proposed market whose window has elapsed with no open dispute.
    /// Never warps, so dispute opportunities aren't skipped.
    function finalizeMarket(uint256 mSeed) external {
        if (marketIds.length == 0) return;
        bytes32 id = _pick(mSeed);
        if (_status(id) != ScalarMarketEngine.Status.Closed) return;
        if (engine.challengerOf(id) != address(0)) return;
        if (block.timestamp < _windowEnd(id)) return;
        engine.finalize(id);
    }

    /// An actor attempts to claim; reverts are swallowed, real payouts credited.
    function claim(uint256 mSeed, uint256 aSeed) external {
        if (marketIds.length == 0) return;
        bytes32 id = _pick(mSeed);
        address who = actors[_bound(aSeed, 0, 3)];

        vm.prank(who);
        try engine.claim(id) returns (uint256 payout) {
            g_totalPaidOut += payout;
        } catch {}
    }

    /// Adversarial: the admin rewrites the global dispute bond (possibly to 0) at an
    /// arbitrary moment — including while challenges are open.
    function churnBond(uint256 seed) external {
        vm.prank(admin);
        engine.setDisputeBond(_bound(seed, 0, MAX_BOND));
    }
}

/// @notice Stateful invariant suite for the scalar engine's dispute/bond mechanism.
///         Runs with a live challenge window and bond and drives the full
///         optimistic-resolution lifecycle with the global bond churning under open
///         challenges, asserting solvency holds once bonds flow through the engine.
contract ScalarMarketEngineDisputeInvariantTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    MockScalarOracle oracle;
    ScalarMarketEngine engine;
    ScalarMarketEngineDisputeHandler handler;

    address admin = address(0xA11CE);
    bytes32 constant OPS = keccak256("OPERATIONS");

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(admin);
        oracle = new MockScalarOracle();
        engine = new ScalarMarketEngine(address(collateral), address(oracle), address(treasury), admin);

        vm.startPrank(admin);
        engine.setChallengeWindow(2 hours);
        engine.setDisputeBond(100e18);
        vm.stopPrank();

        handler = new ScalarMarketEngineDisputeHandler(engine, collateral, oracle, treasury, admin);
        vm.prank(admin);
        engine.setRelayer(address(handler), true);
    }

    function targetContracts() public view returns (address[] memory addrs) {
        addrs = new address[](1);
        addrs[0] = address(handler);
    }

    /// Conservation / solvency including bonds: every token in (stakes + bonds) is
    /// still held, was paid back to a user (claim or refunded bond), or sits in the
    /// treasury (fee or forfeited bond) — even as the global bond churns.
    function invariant_valueIsConservedWithBonds() public view {
        assertEq(
            collateral.balanceOf(address(engine)) + handler.g_totalPaidOut()
                + collateral.balanceOf(address(treasury)),
            handler.g_totalDeposited() + handler.g_totalBondsPosted(),
            "engine + paid + treasury == deposited + bonds"
        );
    }

    /// Every token the treasury holds (fees + forfeited bonds) is in the OPERATIONS bucket.
    function invariant_treasuryBucketReconciles() public view {
        assertEq(
            collateral.balanceOf(address(treasury)),
            treasury.reserves(OPS, address(collateral)),
            "treasury balance == OPERATIONS bucket"
        );
    }

    /// The engine can always cover every bond still locked in an undecided dispute.
    function invariant_openBondsAreBacked() public view {
        assertGe(
            collateral.balanceOf(address(engine)),
            handler.g_openBondTotal(),
            "engine balance >= open bonds"
        );
    }
}
