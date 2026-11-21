// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {ScalarChainlinkAdapter} from "../src/oracle/ScalarChainlinkAdapter.sol";
import {ScalarMarketEngine} from "../src/ScalarMarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockAggregator} from "../src/mocks/MockAggregator.sol";

/// @notice Coverage for the scalar oracle adapter: engine binding, value
///         reporting with decimal rescaling, the shared health logic (reject
///         non-positive, staleness), fallback routing across mismatched
///         decimals, and an end-to-end settle through the ScalarMarketEngine.
contract ScalarChainlinkAdapterTest is MiniTest {
    ScalarChainlinkAdapter adapter;
    MockAggregator feed8; // 8 decimals (e.g. USD price feed)
    MockAggregator feed2; // 2 decimals
    MockAggregator fb6; // 6 decimals (fallback with different scale)

    address constant STRANGER = address(0xBAD);
    bytes32 constant ID = keccak256("scalar-mkt");

    function setUp() public {
        adapter = new ScalarChainlinkAdapter();
        adapter.initEngine(address(this)); // this test acts as the engine
        feed8 = new MockAggregator(8, "ETH / USD");
        feed2 = new MockAggregator(2, "coarse");
        fb6 = new MockAggregator(6, "ETH / USD (backup)");
    }

    // configure to targetDecimals, no fallback, no staleness
    function _cfg(address _feed, address _fb, uint8 targetDec, uint64 maxStale) internal {
        adapter.configure(ID, abi.encode(_feed, _fb, targetDec, maxStale));
    }

    function _value() internal view returns (bool ready, int256 v) {
        return adapter.latestValue(ID);
    }

    // --------------------------------------------------------- engine binding

    function test_initEngine_onlyOnce() public {
        vm.expectRevert(bytes("SORACLE: engine set"));
        adapter.initEngine(address(0xE2));
    }

    function test_initEngine_onlyDeployer() public {
        ScalarChainlinkAdapter fresh = new ScalarChainlinkAdapter();
        vm.prank(STRANGER);
        vm.expectRevert(bytes("SORACLE: not deployer"));
        fresh.initEngine(address(this));
    }

    function test_configure_onlyEngine() public {
        vm.prank(STRANGER);
        vm.expectRevert(bytes("SORACLE: not engine"));
        _cfg(address(feed8), address(0), 0, 0);
    }

    function test_configure_rejectsZeroFeed() public {
        vm.expectRevert(bytes("SORACLE: feed zero"));
        _cfg(address(0), address(0), 0, 0);
    }

    function test_configure_rejectsExcessiveDecimals() public {
        vm.expectRevert(bytes("SORACLE: decimals"));
        _cfg(address(feed8), address(0), 37, 0);
    }

    // ------------------------------------------------------- value + rescale

    function test_unconfigured_isNotReady() public view {
        (bool ready,) = _value();
        assertTrue(!ready, "no config -> not ready");
    }

    function test_rescaleDown_toWholeUnits() public {
        _cfg(address(feed8), address(0), 0, 0); // 8-dec feed -> whole units
        feed8.set(400_000_000_000); // $4000.00000000
        (bool ready, int256 v) = _value();
        assertTrue(ready, "ready");
        assertTrue(v == 4000, "8dec -> 0dec = 4000");
    }

    function test_rescaleUp_addsDecimals() public {
        _cfg(address(feed2), address(0), 4, 0); // 2-dec feed -> 4-dec
        feed2.set(123_45); // 123.45 at 2 decimals
        (, int256 v) = _value();
        assertTrue(v == 1_234_500, "2dec -> 4dec scales up by 100");
    }

    function test_equalDecimals_passthrough() public {
        _cfg(address(feed8), address(0), 8, 0);
        feed8.set(400_000_000_000);
        (, int256 v) = _value();
        assertTrue(v == 400_000_000_000, "no rescale when equal");
    }

    // ------------------------------------------------------- health (shared O1)

    function test_nonPositiveAnswer_isNotReady() public {
        _cfg(address(feed8), address(0), 0, 0);
        feed8.set(-1);
        (bool ready,) = _value();
        assertTrue(!ready, "negative -> not ready");
    }

    function test_zeroAnswer_isNotReady() public {
        _cfg(address(feed8), address(0), 0, 0);
        // never set -> answer 0
        (bool ready,) = _value();
        assertTrue(!ready, "zero -> not ready");
    }

    function test_stale_isNotReady() public {
        _cfg(address(feed8), address(0), 0, 3600);
        feed8.setWithTime(400_000_000_000, block.timestamp);
        vm.warp(block.timestamp + 3601);
        (bool ready,) = _value();
        assertTrue(!ready, "stale -> not ready");
    }

    function test_zeroMaxStale_ignoresAge() public {
        _cfg(address(feed8), address(0), 0, 0);
        feed8.setWithTime(400_000_000_000, 1);
        vm.warp(5_000_000);
        (bool ready, int256 v) = _value();
        assertTrue(ready && v == 4000, "maxStale 0 accepts any age");
    }

    // ------------------------------- fallback across mismatched decimals (O2+)

    function test_fallbackWithDifferentDecimals_rescalesCorrectly() public {
        // primary 8-dec but unhealthy; fallback 6-dec healthy -> both target 0
        _cfg(address(feed8), address(fb6), 0, 0);
        fb6.set(4_000_000_000); // $4000 at 6 decimals
        (bool ready, int256 v) = _value();
        assertTrue(ready && v == 4000, "fallback rescaled from its own decimals");
    }

    function test_bothFeedsUnhealthy_isNotReady() public {
        _cfg(address(feed8), address(fb6), 0, 0);
        (bool ready,) = _value();
        assertTrue(!ready, "no healthy feed -> not ready");
    }

    // ------------------------------ pathological feed decimals fail safe (O5) ---

    function test_pathologicalFeedDecimals_isNotReady() public {
        // A feed reporting decimals > MAX_TARGET_DECIMALS would make _rescale's
        // 10**(from-to) overflow/wrap. It must fail safe (not-ready), never revert.
        MockAggregator huge = new MockAggregator(255, "broken feed");
        huge.set(1_000_000);
        _cfg(address(huge), address(0), 0, 0);
        (bool ready,) = _value(); // does not revert
        assertTrue(!ready, "pathological decimals -> not ready, no revert");
    }

    function test_pathologicalPrimary_fallsBackToSaneFeed() public {
        // primary has absurd decimals (unhealthy); a sane fallback is used instead.
        MockAggregator huge = new MockAggregator(200, "broken feed");
        huge.set(42);
        _cfg(address(huge), address(fb6), 0, 0);
        fb6.set(4_000_000_000); // $4000 at 6 decimals
        (bool ready, int256 v) = _value();
        assertTrue(ready && v == 4000, "fell back past the pathological primary");
    }

    function test_maxFeedDecimals_boundaryAccepted() public {
        // exactly MAX_TARGET_DECIMALS (36) is still a sane, accepted feed.
        MockAggregator d36 = new MockAggregator(36, "36-dec feed");
        d36.set(int256(5 * 10 ** 36)); // value 5 at 36 decimals
        _cfg(address(d36), address(0), 0, 0); // -> whole units
        (bool ready, int256 v) = _value();
        assertTrue(ready && v == 5, "36 decimals accepted, rescaled to 5");
    }

    // -------------------------------------------- end-to-end through the engine

    function test_endToEnd_settlesScalarMarketFromFeed() public {
        // fresh adapter bound to a real engine
        ScalarChainlinkAdapter sa = new ScalarChainlinkAdapter();
        MockERC20 collateral = new MockERC20("USD Coin", "USDC", 18);
        Treasury treasury = new Treasury(address(0xA11CE));
        ScalarMarketEngine engine =
            new ScalarMarketEngine(address(collateral), address(sa), address(treasury), address(this));
        sa.initEngine(address(engine));

        MockAggregator feed = new MockAggregator(8, "ETH / USD");

        address longTrader = address(0x1040);
        address shortTrader = address(0x5401);
        collateral.mint(longTrader, 1_000e18);
        collateral.mint(shortTrader, 1_000e18);
        vm.prank(longTrader);
        collateral.approve(address(engine), type(uint256).max);
        vm.prank(shortTrader);
        collateral.approve(address(engine), type(uint256).max);

        // band [3000, 5000] in whole dollars (targetDecimals 0)
        bytes memory params = abi.encode(address(feed), address(0), uint8(0), uint64(0));
        bytes32 id =
            engine.createMarket(keccak256("ETH settle band?"), uint64(block.timestamp + 1 days), 3000, 5000, params);

        vm.prank(longTrader);
        engine.takePosition(id, ScalarMarketEngine.Side.Long, 600e18);
        vm.prank(shortTrader);
        engine.takePosition(id, ScalarMarketEngine.Side.Short, 400e18);

        // settle: feed reads $4000 -> rescales to 4000 -> f = (4000-3000)/2000 = 0.5
        vm.warp(block.timestamp + 2 days);
        feed.set(400_000_000_000);
        engine.resolve(id);

        ScalarMarketEngine.Market memory m = engine.getMarket(id);
        assertTrue(m.settledValue == 4000, "engine stored rescaled feed value");

        // pot 1000, fee 2% = 20, distributable 980, f=0.5 -> each side pool 490
        vm.prank(longTrader);
        uint256 longOut = engine.claim(id);
        vm.prank(shortTrader);
        uint256 shortOut = engine.claim(id);
        assertEq(longOut, 490e18, "long payout from feed-driven settle");
        assertEq(shortOut, 490e18, "short payout from feed-driven settle");
    }
}
