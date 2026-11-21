// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {MarketEngine} from "../src/MarketEngine.sol";
import {ScalarMarketEngine} from "../src/ScalarMarketEngine.sol";
import {CategoricalMarketEngine} from "../src/CategoricalMarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockOracleAdapter} from "../src/mocks/MockOracleAdapter.sol";
import {MockScalarOracle} from "../src/mocks/MockScalarOracle.sol";
import {MockCategoricalOracle} from "../src/mocks/MockCategoricalOracle.sol";
import {IMarketEngine} from "../src/interfaces/IMarketEngine.sol";
import {IOracleAdapter} from "../src/interfaces/IOracleAdapter.sol";

/// @notice The production deploy (Deploy.s.sol) wires all three engines to a single
///         Treasury and collateral. The per-engine invariants each use their own
///         Treasury, so this is the missing cross-engine property: with binary,
///         scalar, and categorical markets all skimming fees into the *same*
///         Treasury across a randomly-interleaved history, the whole system stays
///         solvent and the Treasury's accounting aggregates every engine's fees
///         exactly. The handler drives all three engines (zero challenge window ->
///         atomic settlement) over a shared set of actors.
contract MultiEngineTreasuryHandler is MiniTest {
    MarketEngine public immutable binaryEngine;
    MockOracleAdapter public immutable binaryOracle;
    ScalarMarketEngine public immutable scalarEngine;
    MockScalarOracle public immutable scalarOracle;
    CategoricalMarketEngine public immutable catEngine;
    MockCategoricalOracle public immutable catOracle;
    MockERC20 public immutable collateral;
    Treasury public immutable treasury;

    address[4] public actors = [address(0xA1), address(0xA2), address(0xB1), address(0xB2)];

    bytes32[] public binIds;
    bytes32[] public scaIds;
    bytes32[] public catIds;
    mapping(bytes32 => uint64) public closeAtOf;
    mapping(bytes32 => bool) public settled;
    mapping(bytes32 => uint8) public outcomeCountOf;

    // --- ghost accounting (read by the invariants) ---
    uint256 public g_totalDeposited;
    uint256 public g_totalPaidOut;

    uint256 constant MIN_STAKE = 1;
    uint256 constant MAX_STAKE = 1e24;

    constructor(
        MarketEngine _b, MockOracleAdapter _bo,
        ScalarMarketEngine _s, MockScalarOracle _so,
        CategoricalMarketEngine _c, MockCategoricalOracle _co,
        MockERC20 _collateral, Treasury _treasury
    ) {
        binaryEngine = _b; binaryOracle = _bo;
        scalarEngine = _s; scalarOracle = _so;
        catEngine = _c; catOracle = _co;
        collateral = _collateral; treasury = _treasury;
    }

    function _actor(uint256 seed) internal view returns (address) {
        return actors[_bound(seed, 0, 3)];
    }

    function _fund(address who, uint256 amount, address engine) internal {
        collateral.mint(who, amount);
        vm.prank(who);
        collateral.approve(engine, amount);
    }

    // ------------------------------------------------------------------ binary
    function binCreate(uint256 seed, uint32 window) external {
        uint64 closeAt = uint64(block.timestamp + _bound(window, 1 hours, 7 days));
        bytes32 qhash = keccak256(abi.encode("b", seed, binIds.length, block.timestamp));
        bytes32 id = binaryEngine.createMarket(qhash, closeAt, uint16(_bound(seed, 0, 10_000)), "");
        binIds.push(id);
        closeAtOf[id] = closeAt;
    }

    function binTake(uint256 mSeed, uint256 aSeed, bool yes, uint96 amt) external {
        if (binIds.length == 0) return;
        bytes32 id = binIds[_bound(mSeed, 0, binIds.length - 1)];
        if (settled[id] || block.timestamp >= closeAtOf[id]) return;
        address who = _actor(aSeed);
        uint256 amount = _bound(amt, MIN_STAKE, MAX_STAKE);
        _fund(who, amount, address(binaryEngine));
        vm.prank(who);
        binaryEngine.takePosition(id, yes ? IMarketEngine.Side.Yes : IMarketEngine.Side.No, amount);
        g_totalDeposited += amount;
    }

    function binResolve(uint256 mSeed, uint8 oSeed) external {
        if (binIds.length == 0) return;
        bytes32 id = binIds[_bound(mSeed, 0, binIds.length - 1)];
        if (settled[id]) return;
        uint64 target = closeAtOf[id] + 1;
        if (block.timestamp < target) vm.warp(target);
        binaryOracle.setOutcome(id, IOracleAdapter.Outcome(uint8(_bound(oSeed, 1, 3))));
        binaryEngine.resolve(id);
        settled[id] = true;
    }

    // ------------------------------------------------------------------ scalar
    function scaCreate(uint256 seed, uint32 window, uint32 widthSeed) external {
        uint64 closeAt = uint64(block.timestamp + _bound(window, 1 hours, 7 days));
        bytes32 qhash = keccak256(abi.encode("s", seed, scaIds.length, block.timestamp));
        int256 lower = int256(_bound(seed, 0, 2000)) - 1000;
        int256 upper = lower + int256(_bound(widthSeed, 1, 1_000_000));
        bytes32 id = scalarEngine.createMarket(qhash, closeAt, lower, upper, "");
        scaIds.push(id);
        closeAtOf[id] = closeAt;
    }

    function scaTake(uint256 mSeed, uint256 aSeed, bool long, uint96 amt) external {
        if (scaIds.length == 0) return;
        bytes32 id = scaIds[_bound(mSeed, 0, scaIds.length - 1)];
        if (settled[id] || block.timestamp >= closeAtOf[id]) return;
        address who = _actor(aSeed);
        uint256 amount = _bound(amt, MIN_STAKE, MAX_STAKE);
        _fund(who, amount, address(scalarEngine));
        vm.prank(who);
        scalarEngine.takePosition(id, long ? ScalarMarketEngine.Side.Long : ScalarMarketEngine.Side.Short, amount);
        g_totalDeposited += amount;
    }

    function scaResolve(uint256 mSeed, uint256 vSeed) external {
        if (scaIds.length == 0) return;
        bytes32 id = scaIds[_bound(mSeed, 0, scaIds.length - 1)];
        if (settled[id]) return;
        uint64 target = closeAtOf[id] + 1;
        if (block.timestamp < target) vm.warp(target);
        // any value; the engine clamps and a one-sided book voids
        scalarOracle.set(id, int256(_bound(vSeed, 0, 2_000_000)) - 1_000_000);
        scalarEngine.resolve(id);
        settled[id] = true;
    }

    // -------------------------------------------------------------- categorical
    function catCreate(uint256 seed, uint32 window) external {
        uint64 closeAt = uint64(block.timestamp + _bound(window, 1 hours, 7 days));
        bytes32 qhash = keccak256(abi.encode("c", seed, catIds.length, block.timestamp));
        uint8 nn = uint8(_bound(seed, 2, 6));
        bytes32 id = catEngine.createMarket(qhash, closeAt, nn, "");
        catIds.push(id);
        closeAtOf[id] = closeAt;
        outcomeCountOf[id] = nn;
    }

    function catTake(uint256 mSeed, uint256 aSeed, uint8 oSeed, uint96 amt) external {
        if (catIds.length == 0) return;
        bytes32 id = catIds[_bound(mSeed, 0, catIds.length - 1)];
        if (settled[id] || block.timestamp >= closeAtOf[id]) return;
        address who = _actor(aSeed);
        uint8 outcome = uint8(_bound(oSeed, 0, outcomeCountOf[id] - 1));
        uint256 amount = _bound(amt, MIN_STAKE, MAX_STAKE);
        _fund(who, amount, address(catEngine));
        vm.prank(who);
        catEngine.takePosition(id, outcome, amount);
        g_totalDeposited += amount;
    }

    function catResolve(uint256 mSeed, uint16 oSeed) external {
        if (catIds.length == 0) return;
        bytes32 id = catIds[_bound(mSeed, 0, catIds.length - 1)];
        if (settled[id]) return;
        uint64 target = closeAtOf[id] + 1;
        if (block.timestamp < target) vm.warp(target);
        if (oSeed % 5 == 0) catOracle.setInvalid(id);
        else catOracle.set(id, uint8(_bound(oSeed, 0, outcomeCountOf[id]))); // N -> void
        catEngine.resolve(id);
        settled[id] = true;
    }

    // ----------------------------------------------------------------- claim any
    function claim(uint256 kind, uint256 mSeed, uint256 aSeed) external {
        address who = _actor(aSeed);
        uint256 k = _bound(kind, 0, 2);
        if (k == 0 && binIds.length > 0) {
            vm.prank(who);
            try binaryEngine.claim(binIds[_bound(mSeed, 0, binIds.length - 1)]) returns (uint256 p) { g_totalPaidOut += p; } catch {}
        } else if (k == 1 && scaIds.length > 0) {
            vm.prank(who);
            try scalarEngine.claim(scaIds[_bound(mSeed, 0, scaIds.length - 1)]) returns (uint256 p) { g_totalPaidOut += p; } catch {}
        } else if (k == 2 && catIds.length > 0) {
            vm.prank(who);
            try catEngine.claim(catIds[_bound(mSeed, 0, catIds.length - 1)]) returns (uint256 p) { g_totalPaidOut += p; } catch {}
        }
    }

    function engineBalances() external view returns (uint256) {
        return collateral.balanceOf(address(binaryEngine))
            + collateral.balanceOf(address(scalarEngine))
            + collateral.balanceOf(address(catEngine));
    }
}

/// @notice Cross-engine solvency around a shared Treasury — the production topology.
contract MultiEngineTreasuryInvariantTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    MarketEngine binaryEngine; MockOracleAdapter binaryOracle;
    ScalarMarketEngine scalarEngine; MockScalarOracle scalarOracle;
    CategoricalMarketEngine catEngine; MockCategoricalOracle catOracle;
    MultiEngineTreasuryHandler handler;

    address admin = address(0xA11CE);
    bytes32 constant OPS = keccak256("OPERATIONS");

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(admin);

        binaryOracle = new MockOracleAdapter();
        binaryEngine = new MarketEngine(address(collateral), address(binaryOracle), address(treasury), admin);
        scalarOracle = new MockScalarOracle();
        scalarEngine = new ScalarMarketEngine(address(collateral), address(scalarOracle), address(treasury), admin);
        catOracle = new MockCategoricalOracle();
        catEngine = new CategoricalMarketEngine(address(collateral), address(catOracle), address(treasury), admin);

        handler = new MultiEngineTreasuryHandler(
            binaryEngine, binaryOracle, scalarEngine, scalarOracle, catEngine, catOracle, collateral, treasury
        );
        vm.startPrank(admin);
        binaryEngine.setRelayer(address(handler), true);
        scalarEngine.setRelayer(address(handler), true);
        catEngine.setRelayer(address(handler), true);
        vm.stopPrank();
    }

    function targetContracts() public view returns (address[] memory addrs) {
        addrs = new address[](1);
        addrs[0] = address(handler);
    }

    /// Whole-system conservation: every token deposited into any of the three
    /// engines is still held by one of them, was paid back out as a claim, or sits
    /// in the shared Treasury as a fee. Nothing leaks across engine boundaries.
    function invariant_systemIsConserved() public view {
        assertEq(
            handler.engineBalances() + handler.g_totalPaidOut() + collateral.balanceOf(address(treasury)),
            handler.g_totalDeposited(),
            "sum(engine balances) + paid + treasury == deposited"
        );
    }

    /// The shared Treasury aggregates every engine's fees into the one OPERATIONS
    /// bucket, and holds exactly that — fees from three independent engine types
    /// reconcile to a single accounting total.
    function invariant_treasuryAggregatesAllEngineFees() public view {
        assertEq(
            collateral.balanceOf(address(treasury)),
            treasury.reserves(OPS, address(collateral)),
            "treasury balance == OPERATIONS bucket (all engines)"
        );
    }
}
