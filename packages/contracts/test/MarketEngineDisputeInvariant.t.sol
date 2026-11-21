// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {MarketEngine} from "../src/MarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockOracleAdapter} from "../src/mocks/MockOracleAdapter.sol";
import {IMarketEngine} from "../src/interfaces/IMarketEngine.sol";
import {IOracleAdapter} from "../src/interfaces/IOracleAdapter.sol";

/// @notice Drives the *optimistic-resolution* path under load: a live challenge
///         window and dispute bond, with randomly-interleaved propose / dispute /
///         arbitrate / finalize / claim across many markets and actors — and an
///         adversarial `churnBond` action that rewrites the global disputeBond
///         while challenges are open. Where the base solvency invariant runs at a
///         zero window (bonds never move), this one makes bonds first-class: it
///         keeps ghost totals of every bond posted, refunded, forfeited, and still
///         locked, so the suite can assert the engine stays solvent once bonds
///         flow through it — the thing the dispute *unit* tests can't reach across
///         an arbitrary history.
contract MarketEngineDisputeHandler is MiniTest {
    MarketEngine public immutable engine;
    MockERC20 public immutable collateral;
    MockOracleAdapter public immutable oracle;
    Treasury public immutable treasury;
    address public immutable admin;

    address[4] public actors = [address(0xA1), address(0xA2), address(0xB1), address(0xB2)];

    bytes32[] public marketIds;
    mapping(bytes32 => uint64) public closeAtOf;

    // --- ghost accounting (read by the invariants) ---
    uint256 public g_totalDeposited; // stakes pulled in
    uint256 public g_totalBondsPosted; // bonds pulled in by dispute()
    uint256 public g_totalPaidOut; // claims + refunded bonds paid back out to users
    uint256 public g_openBondTotal; // bonds currently locked in undecided disputes

    uint256 constant MIN_STAKE = 1;
    uint256 constant MAX_STAKE = 1e24;
    uint256 constant MAX_BOND = 1e24;

    constructor(
        MarketEngine _engine,
        MockERC20 _collateral,
        MockOracleAdapter _oracle,
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

    function _status(bytes32 id) internal view returns (IMarketEngine.Status) {
        return engine.getMarket(id).status;
    }

    function _windowEnd(bytes32 id) internal view returns (uint256) {
        return uint256(engine.proposedAt(id)) + uint256(engine.challengeWindow());
    }

    /// Open a fresh market with a short close so its challenge window is reachable
    /// within a few interleaved steps.
    function createMarket(uint256 seed, uint32 window) external {
        uint64 closeAt = uint64(block.timestamp + _bound(window, 1 hours, 2 hours));
        bytes32 qhash = keccak256(abi.encode(seed, marketIds.length, block.timestamp));
        bytes32 id = engine.createMarket(qhash, closeAt, uint16(_bound(seed, 0, 10_000)), "");
        marketIds.push(id);
        closeAtOf[id] = closeAt;
    }

    /// An actor stakes YES/NO on an open market (within its window).
    function takePosition(uint256 mSeed, uint256 aSeed, bool yes, uint96 amt) external {
        if (marketIds.length == 0) return;
        bytes32 id = _pick(mSeed);
        if (_status(id) != IMarketEngine.Status.Open || block.timestamp >= closeAtOf[id]) return;

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

    /// Warp past close, set an outcome, and resolve — which (window > 0) *proposes*
    /// it and opens the challenge window (status Closed).
    function proposeResolve(uint256 mSeed, uint8 oSeed) external {
        if (marketIds.length == 0) return;
        bytes32 id = _pick(mSeed);
        if (_status(id) != IMarketEngine.Status.Open) return;

        uint64 target = closeAtOf[id] + 1;
        if (block.timestamp < target) vm.warp(target);
        oracle.setOutcome(id, IOracleAdapter.Outcome(uint8(_bound(oSeed, 1, 3)))); // Yes/No/Invalid
        engine.resolve(id);
    }

    /// An actor challenges a proposed outcome within its window, posting the current
    /// global bond (which the engine snapshots). Records the exact amount posted.
    function disputeMarket(uint256 mSeed, uint256 aSeed) external {
        if (marketIds.length == 0) return;
        bytes32 id = _pick(mSeed);
        if (_status(id) != IMarketEngine.Status.Closed) return;
        if (engine.challengerOf(id) != address(0)) return; // already disputed
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

    /// The admin arbitrates an open dispute. The bond is read from the engine's
    /// snapshot *before* arbitration zeroes it: an upheld challenge refunds it to
    /// the challenger (a payout), a rejected one forfeits it to the treasury.
    function arbitrateMarket(uint256 mSeed, uint8 oSeed, bool upheld) external {
        if (marketIds.length == 0) return;
        bytes32 id = _pick(mSeed);
        if (engine.challengerOf(id) == address(0)) return; // nothing to arbitrate

        uint256 bond = engine.bondOf(id);
        IOracleAdapter.Outcome o = IOracleAdapter.Outcome(uint8(_bound(oSeed, 1, 3)));
        vm.prank(admin);
        engine.arbitrate(id, o, upheld);

        g_openBondTotal -= bond;
        if (upheld) g_totalPaidOut += bond; // refunded to the challenger
        // rejected -> forfeited into the treasury (captured by treasury.balanceOf)
    }

    /// Finalize a proposed market whose window has elapsed with no open dispute.
    /// Only fires when time has already advanced past the window (never warps), so
    /// dispute opportunities aren't skipped.
    function finalizeMarket(uint256 mSeed) external {
        if (marketIds.length == 0) return;
        bytes32 id = _pick(mSeed);
        if (_status(id) != IMarketEngine.Status.Closed) return;
        if (engine.challengerOf(id) != address(0)) return;
        if (block.timestamp < _windowEnd(id)) return;
        engine.finalize(id);
    }

    /// An actor attempts to claim. Losers / non-participants / double-claims and
    /// unsettled markets revert inside the engine; the try/catch keeps the sequence
    /// productive and only credits the ghost total on a real payout.
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
    /// arbitrary moment — including while challenges are open. The per-dispute
    /// snapshot must make this irrelevant to every bond already posted.
    function churnBond(uint256 seed) external {
        vm.prank(admin);
        engine.setDisputeBond(_bound(seed, 0, MAX_BOND));
    }
}

/// @notice Stateful invariant suite for the dispute/bond mechanism. Runs with a
///         live challenge window and bond and drives the full optimistic-resolution
///         lifecycle, with the global bond churning underneath open challenges.
///         Proves the engine stays solvent once bonds flow through it, and that the
///         per-dispute bond snapshot makes a mutated global bond harmless.
contract MarketEngineDisputeInvariantTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    MockOracleAdapter oracle;
    MarketEngine engine;
    MarketEngineDisputeHandler handler;

    address admin = address(0xA11CE);
    bytes32 constant OPS = keccak256("OPERATIONS");

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(admin);
        oracle = new MockOracleAdapter();
        engine = new MarketEngine(address(collateral), address(oracle), address(treasury), admin);

        vm.startPrank(admin);
        engine.setChallengeWindow(2 hours); // disputes are live
        engine.setDisputeBond(100e18);
        vm.stopPrank();

        handler = new MarketEngineDisputeHandler(engine, collateral, oracle, treasury, admin);
        vm.prank(admin);
        engine.setRelayer(address(handler), true);
    }

    /// Only the handler's actions are fuzzed (forge reads this getter).
    function targetContracts() public view returns (address[] memory addrs) {
        addrs = new address[](1);
        addrs[0] = address(handler);
    }

    /// Conservation / solvency *including bonds*: every token that entered the
    /// engine — stakes and posted bonds — is still held (open pots, open bonds,
    /// floor-division dust), was paid back to a user (a claim or a refunded bond),
    /// or sits in the treasury (a market fee or a forfeited bond). Nothing leaks,
    /// even as the global bond churns under open disputes.
    function invariant_valueIsConservedWithBonds() public view {
        assertEq(
            collateral.balanceOf(address(engine)) + handler.g_totalPaidOut()
                + collateral.balanceOf(address(treasury)),
            handler.g_totalDeposited() + handler.g_totalBondsPosted(),
            "engine + paid + treasury == deposited + bonds"
        );
    }

    /// Every token the treasury holds (fees + forfeited bonds) is accounted for in
    /// the OPERATIONS bucket — forfeited bonds land there exactly like fees.
    function invariant_treasuryBucketReconciles() public view {
        assertEq(
            collateral.balanceOf(address(treasury)),
            treasury.reserves(OPS, address(collateral)),
            "treasury balance == OPERATIONS bucket"
        );
    }

    /// The engine can always cover every bond still locked in an undecided dispute:
    /// posted bonds are never spent until arbitration settles them.
    function invariant_openBondsAreBacked() public view {
        assertGe(
            collateral.balanceOf(address(engine)),
            handler.g_openBondTotal(),
            "engine balance >= open bonds"
        );
    }
}
