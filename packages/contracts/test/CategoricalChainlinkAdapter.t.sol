// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {CategoricalChainlinkAdapter} from "../src/oracle/CategoricalChainlinkAdapter.sol";
import {CategoricalMarketEngine} from "../src/CategoricalMarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockAggregator} from "../src/mocks/MockAggregator.sol";

/// @notice Coverage for the categorical oracle adapter: engine binding, winning-
///         index reporting, the health posture (0 is a valid index, negative and
///         zero-timestamp are not, staleness), the out-of-range -> void sentinel,
///         fallback routing, and an end-to-end settle through the
///         CategoricalMarketEngine.
contract CategoricalChainlinkAdapterTest is MiniTest {
    CategoricalChainlinkAdapter adapter;
    MockAggregator feed; // reports a winning index
    MockAggregator fb; // fallback

    address constant STRANGER = address(0xBAD);
    bytes32 constant ID = keccak256("cat-mkt");

    function setUp() public {
        adapter = new CategoricalChainlinkAdapter();
        adapter.initEngine(address(this)); // this test acts as the engine
        feed = new MockAggregator(0, "MATCH RESULT");
        fb = new MockAggregator(0, "MATCH RESULT (backup)");
    }

    function _cfg(address _feed, address _fb, uint64 maxStale) internal {
        adapter.configure(ID, abi.encode(_feed, _fb, maxStale));
    }

    function _outcome() internal view returns (bool ready, uint8 o) {
        return adapter.latestOutcome(ID);
    }

    // --------------------------------------------------------- engine binding

    function test_initEngine_onlyOnce() public {
        vm.expectRevert(bytes("CORACLE: engine set"));
        adapter.initEngine(address(0xE2));
    }

    function test_initEngine_onlyDeployer() public {
        CategoricalChainlinkAdapter fresh = new CategoricalChainlinkAdapter();
        vm.prank(STRANGER);
        vm.expectRevert(bytes("CORACLE: not deployer"));
        fresh.initEngine(address(this));
    }

    function test_configure_onlyEngine() public {
        vm.prank(STRANGER);
        vm.expectRevert(bytes("CORACLE: not engine"));
        _cfg(address(feed), address(0), 0);
    }

    function test_configure_rejectsZeroFeed() public {
        vm.expectRevert(bytes("CORACLE: feed zero"));
        _cfg(address(0), address(0), 0);
    }

    // --------------------------------------------------------- reporting

    function test_unconfigured_isNotReady() public view {
        (bool ready,) = _outcome();
        assertTrue(!ready, "unconfigured -> not ready");
    }

    function test_reportsWinningIndex() public {
        _cfg(address(feed), address(0), 0);
        feed.set(2);
        (bool ready, uint8 o) = _outcome();
        assertTrue(ready, "ready");
        assertEq(uint256(o), 2, "winning index 2");
    }

    function test_zeroIsAValidIndex() public {
        // unlike the scalar adapter (which rejects <= 0), outcome 0 is valid here
        _cfg(address(feed), address(0), 0);
        feed.set(0);
        (bool ready, uint8 o) = _outcome();
        assertTrue(ready, "ready on index 0");
        assertEq(uint256(o), 0, "index 0");
    }

    function test_negativeAnswerIsNotReady() public {
        _cfg(address(feed), address(0), 0);
        feed.set(-1);
        (bool ready,) = _outcome();
        assertTrue(!ready, "negative -> not ready (fail-safe)");
    }

    function test_zeroTimestampIsNotReady() public {
        _cfg(address(feed), address(0), 0);
        feed.setWithTime(1, 0); // uninitialized timestamp
        (bool ready,) = _outcome();
        assertTrue(!ready, "zero timestamp -> not ready");
    }

    function test_outOfRangeAnswerVoidsViaSentinel() public {
        _cfg(address(feed), address(0), 0);
        feed.set(300); // > uint8 max -> out of any valid outcome range
        (bool ready, uint8 o) = _outcome();
        assertTrue(ready, "ready");
        assertEq(uint256(o), 255, "reports the invalid sentinel (void)");
    }

    // --------------------------------------------------------- staleness

    function test_staleAnswerIsNotReady() public {
        _cfg(address(feed), address(0), 3600);
        feed.set(1);
        vm.warp(block.timestamp + 4000); // beyond maxStale
        (bool ready,) = _outcome();
        assertTrue(!ready, "stale -> not ready");
    }

    function test_zeroMaxStaleDisablesStalenessCheck() public {
        _cfg(address(feed), address(0), 0);
        feed.set(1);
        vm.warp(block.timestamp + 10_000 days);
        (bool ready, uint8 o) = _outcome();
        assertTrue(ready, "maxStale 0 -> never stale");
        assertEq(uint256(o), 1, "index 1");
    }

    // --------------------------------------------------------- fallback

    function test_fallbackUsedWhenPrimaryUnhealthy() public {
        _cfg(address(feed), address(fb), 0);
        feed.setWithTime(1, 0); // primary unhealthy (zero timestamp)
        fb.set(3); // fallback healthy
        (bool ready, uint8 o) = _outcome();
        assertTrue(ready, "fallback read");
        assertEq(uint256(o), 3, "fallback winning index");
    }

    function test_bothFeedsUnhealthyIsNotReady() public {
        _cfg(address(feed), address(fb), 0);
        feed.set(-1);
        fb.setWithTime(1, 0);
        (bool ready,) = _outcome();
        assertTrue(!ready, "no healthy feed -> not ready");
    }

    // --------------------------------------------------------- end to end

    /// Settle a real CategoricalMarketEngine market through this adapter.
    function test_endToEnd_settleThroughEngine() public {
        MockERC20 collateral = new MockERC20("USD Coin", "USDC", 18);
        Treasury treasury = new Treasury(address(this));
        CategoricalChainlinkAdapter oracle = new CategoricalChainlinkAdapter();
        CategoricalMarketEngine engine =
            new CategoricalMarketEngine(address(collateral), address(oracle), address(treasury), address(this));
        oracle.initEngine(address(engine));

        MockAggregator resultFeed = new MockAggregator(0, "RESULT");

        address alice = address(0xA1);
        address bob = address(0xB0);
        collateral.mint(alice, 1_000e18);
        collateral.mint(bob, 1_000e18);
        vm.prank(alice);
        collateral.approve(address(engine), type(uint256).max);
        vm.prank(bob);
        collateral.approve(address(engine), type(uint256).max);

        bytes32 id = engine.createMarket(
            keccak256("who wins?"), uint64(block.timestamp + 1 days), 3,
            abi.encode(address(resultFeed), address(0), uint64(0))
        );
        vm.prank(alice);
        engine.takePosition(id, 0, 600e18);
        vm.prank(bob);
        engine.takePosition(id, 1, 400e18);

        resultFeed.set(0); // outcome 0 wins
        vm.warp(block.timestamp + 2 days);
        engine.resolve(id);

        // outcome 0 wins: losing 400, fee 2% = 8, distributable 392
        // Alice 600 + 392 = 992 (e18 units)
        vm.prank(alice);
        uint256 payout = engine.claim(id);
        assertEq(payout, 992e18, "alice settled through the adapter");
    }
}
