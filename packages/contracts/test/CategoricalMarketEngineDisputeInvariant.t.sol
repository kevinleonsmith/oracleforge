// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {CategoricalMarketEngine} from "../src/CategoricalMarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockCategoricalOracle} from "../src/mocks/MockCategoricalOracle.sol";

/// @notice Drives the categorical engine's optimistic-resolution path under load: a
///         live challenge window and dispute bond, with randomly-interleaved
///         propose / dispute / arbitrate / finalize / claim across many N-outcome
///         markets and actors, and an adversarial `churnBond` action rewriting the
///         global disputeBond while challenges are open. Unlike the scalar engine,
///         every resolve *proposes* (the void decisions are deferred to finalize),
///         so disputes can be raised on any proposed market — including ones that
///         will ultimately void. The admin's arbitration can itself move the
///         outcome to an out-of-range index, voiding at finalize. Bonds are
///         first-class ghost state, so the suite asserts solvency once bonds flow.
contract CategoricalMarketEngineDisputeHandler is MiniTest {
    CategoricalMarketEngine public immutable engine;
    MockERC20 public immutable collateral;
    MockCategoricalOracle public immutable oracle;
    Treasury public immutable treasury;
    address public immutable admin;

    address[4] public actors = [address(0xA1), address(0xA2), address(0xB1), address(0xB2)];

    bytes32[] public marketIds;
    mapping(bytes32 => uint64) public closeAtOf;
    mapping(bytes32 => uint8) public outcomeCountOf;

    // --- ghost accounting (read by the invariants) ---
    uint256 public g_totalDeposited; // stakes pulled in
    uint256 public g_totalBondsPosted; // bonds pulled in by dispute()
    uint256 public g_totalPaidOut; // claims + refunded bonds paid back out to users
    uint256 public g_openBondTotal; // bonds currently locked in undecided disputes

    uint256 constant MIN_STAKE = 1;
    uint256 constant MAX_STAKE = 1e24;
    uint256 constant MAX_BOND = 1e24;
    uint8 constant MIN_OUTCOMES = 2;
    uint8 constant MAX_OUTCOMES = 6;

    constructor(
        CategoricalMarketEngine _engine,
        MockERC20 _collateral,
        MockCategoricalOracle _oracle,
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

    function _status(bytes32 id) internal view returns (CategoricalMarketEngine.Status) {
        return engine.getMarket(id).status;
    }

    function _windowEnd(bytes32 id) internal view returns (uint256) {
        return uint256(engine.proposedAt(id)) + uint256(engine.challengeWindow());
    }

    /// Open a fresh N-outcome market with a short close; N random in [2, 6].
    function createMarket(uint256 seed, uint32 window) external {
        uint64 closeAt = uint64(block.timestamp + _bound(window, 1 hours, 2 hours));
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
        bytes32 id = _pick(mSeed);
        if (_status(id) != CategoricalMarketEngine.Status.Open || block.timestamp >= closeAtOf[id]) return;

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

    /// Warp past close, name a winning outcome (or the invalid sentinel), and
    /// resolve — which always *proposes* (status Closed); the void is decided later.
    function proposeResolve(uint256 mSeed, uint16 oSeed) external {
        if (marketIds.length == 0) return;
        bytes32 id = _pick(mSeed);
        if (_status(id) != CategoricalMarketEngine.Status.Open) return;

        uint64 target = closeAtOf[id] + 1;
        if (block.timestamp < target) vm.warp(target);
        if (oSeed % 5 == 0) {
            oracle.setInvalid(id);
        } else {
            oracle.set(id, uint8(_bound(oSeed, 0, outcomeCountOf[id]))); // N -> out of range
        }
        engine.resolve(id);
    }

    /// An actor challenges a proposed outcome within its window, posting the current
    /// global bond (which the engine snapshots). Records the exact amount posted.
    function disputeMarket(uint256 mSeed, uint256 aSeed) external {
        if (marketIds.length == 0) return;
        bytes32 id = _pick(mSeed);
        if (_status(id) != CategoricalMarketEngine.Status.Closed) return;
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

    /// The admin arbitrates an open dispute with an authoritative outcome — which
    /// may be a funded winner, an empty outcome, or (index == N) an out-of-range
    /// void. The bond is read from the snapshot before arbitration zeroes it.
    function arbitrateMarket(uint256 mSeed, uint16 oSeed, bool upheld) external {
        if (marketIds.length == 0) return;
        bytes32 id = _pick(mSeed);
        if (engine.challengerOf(id) == address(0)) return;

        uint256 bond = engine.bondOf(id);
        uint8 finalOutcome = uint8(_bound(oSeed, 0, outcomeCountOf[id])); // N -> void
        vm.prank(admin);
        engine.arbitrate(id, finalOutcome, upheld);

        g_openBondTotal -= bond;
        if (upheld) g_totalPaidOut += bond;
    }

    /// Finalize a proposed market whose window has elapsed with no open dispute.
    /// Never warps, so dispute opportunities aren't skipped.
    function finalizeMarket(uint256 mSeed) external {
        if (marketIds.length == 0) return;
        bytes32 id = _pick(mSeed);
        if (_status(id) != CategoricalMarketEngine.Status.Closed) return;
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

/// @notice Stateful invariant suite for the categorical engine's dispute/bond
///         mechanism. Runs with a live challenge window and bond and drives the full
///         optimistic-resolution lifecycle — including arbitrations that void — with
///         the global bond churning under open challenges, asserting solvency holds
///         once bonds flow through the engine.
contract CategoricalMarketEngineDisputeInvariantTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    MockCategoricalOracle oracle;
    CategoricalMarketEngine engine;
    CategoricalMarketEngineDisputeHandler handler;

    address admin = address(0xA11CE);
    bytes32 constant OPS = keccak256("OPERATIONS");

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(admin);
        oracle = new MockCategoricalOracle();
        engine = new CategoricalMarketEngine(address(collateral), address(oracle), address(treasury), admin);

        vm.startPrank(admin);
        engine.setChallengeWindow(2 hours);
        engine.setDisputeBond(100e18);
        vm.stopPrank();

        handler = new CategoricalMarketEngineDisputeHandler(engine, collateral, oracle, treasury, admin);
        vm.prank(admin);
        engine.setRelayer(address(handler), true);
    }

    function targetContracts() public view returns (address[] memory addrs) {
        addrs = new address[](1);
        addrs[0] = address(handler);
    }

    /// Conservation / solvency including bonds: every token in (stakes + bonds) is
    /// still held, was paid back to a user (claim or refunded bond), or sits in the
    /// treasury (fee or forfeited bond) — even as the global bond churns and
    /// arbitrations void markets.
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
