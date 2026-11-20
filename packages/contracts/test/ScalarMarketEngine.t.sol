// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {ScalarMarketEngine} from "../src/ScalarMarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockScalarOracle} from "../src/mocks/MockScalarOracle.sol";

/// @notice Lifecycle + settlement coverage for the scalar (range) engine: band
///         validation, LONG/SHORT positions, proportional settlement at clamp
///         boundaries and mid-band, fee snapshotting, one-sided void, and the
///         value-conservation property on a concrete book.
contract ScalarMarketEngineTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    MockScalarOracle oracle;
    ScalarMarketEngine engine;

    address admin = address(0xA11CE);
    address alice = address(0xA1);
    address bob = address(0xB0);
    address carol = address(0xCA);

    int256 constant LOWER = 100;
    int256 constant UPPER = 200;
    bytes32 marketId;

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(admin);
        oracle = new MockScalarOracle();
        engine = new ScalarMarketEngine(address(collateral), address(oracle), address(treasury), admin);

        for (uint256 i; i < 3; i++) {
            address who = [alice, bob, carol][i];
            collateral.mint(who, 10_000e18);
            vm.prank(who);
            collateral.approve(address(engine), type(uint256).max);
        }
    }

    function _create() internal returns (bytes32 id) {
        vm.prank(admin);
        id = engine.createMarket(keccak256("ETH range?"), uint64(block.timestamp + 7 days), LOWER, UPPER, "");
    }

    function _take(bytes32 id, address who, ScalarMarketEngine.Side side, uint256 amt) internal {
        vm.prank(who);
        engine.takePosition(id, side, amt);
    }

    function _resolveAt(bytes32 id, int256 value) internal {
        vm.warp(block.timestamp + 8 days);
        oracle.set(id, value);
        engine.resolve(id);
    }

    function _claim(bytes32 id, address who) internal returns (uint256) {
        vm.prank(who);
        return engine.claim(id);
    }

    // ------------------------------------------------------------- creation

    function test_create_storesBand() public {
        marketId = _create();
        ScalarMarketEngine.Market memory m = engine.getMarket(marketId);
        assertTrue(m.lower == LOWER && m.upper == UPPER, "band stored");
        assertEq(uint256(m.feeBps), 200, "fee snapshot");
        assertEq(uint256(uint8(m.status)), 0, "open");
    }

    function test_create_rejectsInvertedBand() public {
        vm.prank(admin);
        vm.expectRevert(bytes("SCALAR: band"));
        engine.createMarket(keccak256("x"), uint64(block.timestamp + 1 days), 200, 100, "");
    }

    function test_create_onlyRelayer() public {
        vm.prank(alice);
        vm.expectRevert(bytes("SCALAR: not relayer"));
        engine.createMarket(keccak256("x"), uint64(block.timestamp + 1 days), LOWER, UPPER, "");
    }

    // --------------------------------------------------------- positions

    function test_takePosition_accumulatesPools() public {
        marketId = _create();
        _take(marketId, alice, ScalarMarketEngine.Side.Long, 600e18);
        _take(marketId, bob, ScalarMarketEngine.Side.Short, 400e18);
        ScalarMarketEngine.Market memory m = engine.getMarket(marketId);
        assertEq(m.longPool, 600e18, "long pool");
        assertEq(m.shortPool, 400e18, "short pool");
    }

    // ---------------------------------------------- settlement (mid-band)

    function test_settle_midband_splitsProRata() public {
        marketId = _create();
        _take(marketId, alice, ScalarMarketEngine.Side.Long, 600e18);
        _take(marketId, bob, ScalarMarketEngine.Side.Short, 400e18);
        // pot 1000, fee 2% = 20, distributable 980; v=150 => f=0.5
        _resolveAt(marketId, 150);

        ScalarMarketEngine.Market memory m = engine.getMarket(marketId);
        assertTrue(m.settledValue == 150, "settled value");
        assertEq(uint256(uint8(m.status)), 2, "resolved");

        // long side pool = 490, short side pool = 490
        uint256 aliceOut = _claim(marketId, alice); // sole long: 490 * 600/600
        uint256 bobOut = _claim(marketId, bob); // sole short: 490 * 400/400
        assertEq(aliceOut, 490e18, "long payout");
        assertEq(bobOut, 490e18, "short payout");
        assertEq(collateral.balanceOf(address(treasury)), 20e18, "fee to treasury");
        // conservation: payouts + fee == deposits, engine emptied
        assertEq(aliceOut + bobOut + 20e18, 1000e18, "value conserved");
        assertEq(collateral.balanceOf(address(engine)), 0, "engine empty");
    }

    function test_settle_atLowerBound_longGetsNothing() public {
        marketId = _create();
        _take(marketId, alice, ScalarMarketEngine.Side.Long, 500e18);
        _take(marketId, bob, ScalarMarketEngine.Side.Short, 500e18);
        _resolveAt(marketId, 50); // clamps to lower => f=0
        assertEq(_claim(marketId, alice), 0, "long gets zero at/below lower");
        assertEq(_claim(marketId, bob), 980e18, "short takes all distributable");
    }

    function test_settle_atUpperBound_shortGetsNothing() public {
        marketId = _create();
        _take(marketId, alice, ScalarMarketEngine.Side.Long, 500e18);
        _take(marketId, bob, ScalarMarketEngine.Side.Short, 500e18);
        _resolveAt(marketId, 999); // clamps to upper => f=1
        assertEq(_claim(marketId, alice), 980e18, "long takes all distributable");
        assertEq(_claim(marketId, bob), 0, "short gets zero at/above upper");
    }

    function test_settle_intraSideProRata_conserves() public {
        marketId = _create();
        // two longs, one short
        _take(marketId, alice, ScalarMarketEngine.Side.Long, 400e18);
        _take(marketId, carol, ScalarMarketEngine.Side.Long, 200e18);
        _take(marketId, bob, ScalarMarketEngine.Side.Short, 400e18);
        _resolveAt(marketId, 150); // f=0.5, distributable 980, longPool pays 490

        uint256 a = _claim(marketId, alice); // 490 * 400/600
        uint256 c = _claim(marketId, carol); // 490 * 200/600
        uint256 b = _claim(marketId, bob); // 490 * 400/400
        // sum of payouts + fee + dust == total deposits
        uint256 deposits = 1000e18;
        uint256 paid = a + b + c;
        uint256 dust = collateral.balanceOf(address(engine));
        assertEq(paid + 20e18 + dust, deposits, "conserved with dust in engine");
        assertLe(dust, 2, "dust is sub-wei-scale rounding only");
    }

    // ------------------------------------------------------- void / guards

    function test_oneSidedBook_voids_refundsPrincipal() public {
        marketId = _create();
        _take(marketId, alice, ScalarMarketEngine.Side.Long, 300e18); // no shorts
        _resolveAt(marketId, 150);
        ScalarMarketEngine.Market memory m = engine.getMarket(marketId);
        assertEq(uint256(uint8(m.status)), 3, "invalid/void");
        assertEq(_claim(marketId, alice), 300e18, "principal refunded");
        assertEq(collateral.balanceOf(address(treasury)), 0, "no fee on void");
    }

    function test_resolve_revertsWhenOraclePending() public {
        marketId = _create();
        _take(marketId, alice, ScalarMarketEngine.Side.Long, 100e18);
        _take(marketId, bob, ScalarMarketEngine.Side.Short, 100e18);
        vm.warp(block.timestamp + 8 days);
        // oracle never set => not ready
        vm.expectRevert(bytes("SCALAR: oracle pending"));
        engine.resolve(marketId);
    }

    function test_feeFixedAtCreation_notResolve() public {
        marketId = _create(); // snapshots 2%
        _take(marketId, alice, ScalarMarketEngine.Side.Long, 500e18);
        _take(marketId, bob, ScalarMarketEngine.Side.Short, 500e18);
        vm.prank(admin);
        engine.setFeeBps(1000); // admin hikes global to 10%
        _resolveAt(marketId, 150);
        // still skims the market's original 2% = 20, not 100
        assertEq(collateral.balanceOf(address(treasury)), 20e18, "original fee honored");
    }

    function test_claim_guards() public {
        marketId = _create();
        _take(marketId, alice, ScalarMarketEngine.Side.Long, 500e18);
        _take(marketId, bob, ScalarMarketEngine.Side.Short, 500e18);
        _resolveAt(marketId, 150);
        _claim(marketId, alice);
        vm.prank(alice);
        vm.expectRevert(bytes("SCALAR: claimed"));
        engine.claim(marketId);
        // carol never staked
        vm.prank(carol);
        vm.expectRevert(bytes("SCALAR: no stake"));
        engine.claim(marketId);
    }

    // --------------------------------------------------- hardened posture

    function test_admin_twoStepRotation() public {
        vm.prank(admin);
        engine.transferAdmin(alice);
        assertEq(engine.admin(), admin, "unchanged until accepted");
        vm.prank(alice);
        engine.acceptAdmin();
        assertEq(engine.admin(), alice, "rotated");
    }

    function test_constructor_rejectsZeroAdmin() public {
        vm.expectRevert(bytes("SCALAR: admin zero"));
        new ScalarMarketEngine(address(collateral), address(oracle), address(treasury), address(0));
    }
}
