// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {ChainlinkOracleAdapter} from "../src/oracle/ChainlinkOracleAdapter.sol";
import {IOracleAdapter} from "../src/interfaces/IOracleAdapter.sol";
import {MockAggregator} from "../src/mocks/MockAggregator.sol";

/// @notice Focused review coverage for ChainlinkOracleAdapter — the last core
///         contract that was only exercised through MarketEngine. Covers the
///         engine binding, comparator semantics, the staleness guard, fallback
///         routing, and the review fixes O1 (reject non-positive answers) and
///         O2 (fallback must share the primary's decimals).
contract ChainlinkOracleAdapterTest is MiniTest {
    ChainlinkOracleAdapter oracle;
    MockAggregator feed; // 8 decimals
    MockAggregator fb; // 8 decimals (valid fallback)
    MockAggregator fb6; // 6 decimals (mismatched)

    // this test contract plays the role of the engine
    address constant STRANGER = address(0xBAD);
    bytes32 constant ID = keccak256("mkt");
    int256 constant THRESHOLD = 110_000_000; // 1.10 at 8 decimals

    function _P() internal pure returns (uint8) { return uint8(IOracleAdapter.Outcome.Pending); }
    function _Y() internal pure returns (uint8) { return uint8(IOracleAdapter.Outcome.Yes); }
    function _N() internal pure returns (uint8) { return uint8(IOracleAdapter.Outcome.No); }

    function setUp() public {
        oracle = new ChainlinkOracleAdapter();
        oracle.initEngine(address(this)); // deployer binds the engine (= this)
        feed = new MockAggregator(8, "EUR / USD");
        fb = new MockAggregator(8, "EUR / USD (backup)");
        fb6 = new MockAggregator(6, "wrong scale");
    }

    function _cfg(address _feed, address _fb, uint8 cmp, uint64 maxStale) internal {
        oracle.configure(ID, abi.encode(_feed, _fb, THRESHOLD, cmp, maxStale));
    }

    function _resolve() internal view returns (uint8) {
        return uint8(oracle.resolve(ID));
    }

    // ------------------------------------------------------------ engine binding

    function test_initEngine_onlyOnce() public {
        vm.expectRevert(bytes("ORACLE: engine set"));
        oracle.initEngine(address(0xE2));
    }

    function test_initEngine_onlyDeployer() public {
        ChainlinkOracleAdapter fresh = new ChainlinkOracleAdapter();
        vm.prank(STRANGER);
        vm.expectRevert(bytes("ORACLE: not deployer"));
        fresh.initEngine(address(this));
    }

    function test_configure_onlyEngine() public {
        vm.prank(STRANGER);
        vm.expectRevert(bytes("ORACLE: not engine"));
        _cfg(address(feed), address(0), 0, 0);
    }

    function test_configure_rejectsZeroFeed() public {
        vm.expectRevert(bytes("ORACLE: feed zero"));
        _cfg(address(0), address(0), 0, 0);
    }

    function test_configure_rejectsBadComparator() public {
        vm.expectRevert(bytes("ORACLE: comparator"));
        oracle.configure(ID, abi.encode(address(feed), address(0), THRESHOLD, uint8(2), uint64(0)));
    }

    // ------------------------------------------------------------- resolution

    function test_unconfigured_isPending() public view {
        assertEq(uint256(_resolve()), _P(), "no config -> pending");
    }

    function test_gte_comparator() public {
        _cfg(address(feed), address(0), 0, 0); // YES iff answer >= threshold
        feed.set(112_000_000);
        assertEq(uint256(_resolve()), _Y(), "above -> yes");
        feed.set(108_000_000);
        assertEq(uint256(_resolve()), _N(), "below -> no");
        feed.set(THRESHOLD);
        assertEq(uint256(_resolve()), _Y(), "at threshold -> yes");
    }

    function test_lte_comparator() public {
        _cfg(address(feed), address(0), 1, 0); // YES iff answer <= threshold
        feed.set(108_000_000);
        assertEq(uint256(_resolve()), _Y(), "below -> yes");
        feed.set(112_000_000);
        assertEq(uint256(_resolve()), _N(), "above -> no");
        feed.set(THRESHOLD);
        assertEq(uint256(_resolve()), _Y(), "at threshold -> yes");
    }

    // ----------------------------------------------------- O1: unhealthy answers

    function test_zeroAnswer_isPending() public {
        _cfg(address(feed), address(0), 0, 0);
        // fresh feed has answer 0 (never set) -> unhealthy, not resolved
        assertEq(uint256(_resolve()), _P(), "zero answer -> pending");
    }

    function test_negativeAnswer_isPending_notResolved() public {
        _cfg(address(feed), address(0), 1, 0); // <= threshold would read YES for a negative
        feed.set(-5);
        assertEq(uint256(_resolve()), _P(), "negative answer rejected -> pending (fail-safe)");
    }

    // ------------------------------------------------------------- staleness

    function test_staleFeed_isPending() public {
        _cfg(address(feed), address(0), 0, 3600); // 1h max staleness
        feed.setWithTime(112_000_000, block.timestamp); // fresh
        vm.warp(block.timestamp + 3601); // now older than maxStale
        assertEq(uint256(_resolve()), _P(), "stale -> pending");
    }

    function test_zeroMaxStale_ignoresAge() public {
        _cfg(address(feed), address(0), 0, 0); // staleness disabled
        feed.setWithTime(112_000_000, 1); // ancient timestamp
        vm.warp(10_000_000);
        assertEq(uint256(_resolve()), _Y(), "maxStale 0 accepts any age");
    }

    // -------------------------------------------------------- fallback routing

    function test_fallbackUsed_whenPrimaryUnhealthy() public {
        _cfg(address(feed), address(fb), 0, 0);
        // primary never set (answer 0 -> unhealthy); fallback healthy and above
        fb.set(112_000_000);
        assertEq(uint256(_resolve()), _Y(), "resolves from fallback");
    }

    function test_bothFeedsUnhealthy_isPending() public {
        _cfg(address(feed), address(fb), 0, 0);
        // neither set -> both answer 0 -> pending
        assertEq(uint256(_resolve()), _P(), "no healthy feed -> pending");
    }

    function test_primaryPreferredOverFallback() public {
        _cfg(address(feed), address(fb), 0, 0);
        feed.set(112_000_000); // primary healthy, above
        fb.set(108_000_000); // fallback would say NO, but must be ignored
        assertEq(uint256(_resolve()), _Y(), "primary wins when healthy");
    }

    // ------------------------------------------------ O2: fallback decimals guard

    function test_configure_rejectsFallbackDecimalMismatch() public {
        vm.expectRevert(bytes("ORACLE: feed decimals"));
        _cfg(address(feed), address(fb6), 0, 0); // 8 vs 6 decimals
    }

    function test_configure_acceptsMatchingFallbackDecimals() public {
        _cfg(address(feed), address(fb), 0, 0); // both 8 decimals -> ok
        feed.set(112_000_000);
        assertEq(uint256(_resolve()), _Y(), "configured and resolvable");
    }
}
