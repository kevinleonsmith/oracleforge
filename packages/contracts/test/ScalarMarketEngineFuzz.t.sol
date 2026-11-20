// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {ScalarMarketEngine} from "../src/ScalarMarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockScalarOracle} from "../src/mocks/MockScalarOracle.sol";

/// @notice Property tests for scalar settlement: value is conserved across any
///         book and settlement point, and LONG payout is monotone in the
///         settlement value (higher value never pays LONG less).
contract ScalarMarketEngineFuzzTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    MockScalarOracle oracle;
    ScalarMarketEngine engine;

    address admin = address(0xA11CE);
    address la = address(0x1A);
    address lb = address(0x1B);
    address sa = address(0x25);
    address sb = address(0x26);

    int256 constant LOWER = 1_000;
    int256 constant UPPER = 2_000;
    uint256 constant MIN = 1e15;
    uint256 constant MAX = 1e27;

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(admin);
        oracle = new MockScalarOracle();
        engine = new ScalarMarketEngine(address(collateral), address(oracle), address(treasury), admin);
        address[4] memory who = [la, lb, sa, sb];
        for (uint256 i; i < 4; i++) {
            collateral.mint(who[i], 1e30);
            vm.prank(who[i]);
            collateral.approve(address(engine), type(uint256).max);
        }
    }

    function _market(bytes32 salt) internal returns (bytes32 id) {
        vm.prank(admin);
        id = engine.createMarket(salt, uint64(block.timestamp + 1 days), LOWER, UPPER, "");
    }

    function _take(bytes32 id, address who, ScalarMarketEngine.Side side, uint256 amt) internal {
        vm.prank(who);
        engine.takePosition(id, side, amt);
    }

    function _claim(bytes32 id, address who) internal returns (uint256) {
        vm.prank(who);
        return engine.claim(id);
    }

    /// Value is conserved for any book and any settlement value: the sum of all
    /// payouts, the treasury fee, and the sub-wei rounding dust left in the engine
    /// exactly equals total deposits.
    function testFuzz_settlementConservesValue(
        uint256 l1,
        uint256 l2,
        uint256 s1,
        uint256 s2,
        int256 rawValue
    ) public {
        l1 = _bound(l1, MIN, MAX);
        l2 = _bound(l2, MIN, MAX);
        s1 = _bound(s1, MIN, MAX);
        s2 = _bound(s2, MIN, MAX);

        bytes32 id = _market(keccak256("conserve"));
        _take(id, la, ScalarMarketEngine.Side.Long, l1);
        _take(id, lb, ScalarMarketEngine.Side.Long, l2);
        _take(id, sa, ScalarMarketEngine.Side.Short, s1);
        _take(id, sb, ScalarMarketEngine.Side.Short, s2);

        vm.warp(block.timestamp + 2 days);
        oracle.set(id, rawValue); // any value; the engine clamps into the band
        engine.resolve(id);

        uint256 deposits = l1 + l2 + s1 + s2;
        uint256 fee = collateral.balanceOf(address(treasury));

        uint256 paid = _claim(id, la) + _claim(id, lb) + _claim(id, sa) + _claim(id, sb);
        uint256 dust = collateral.balanceOf(address(engine));

        assertEq(paid + fee + dust, deposits, "payouts + fee + dust == deposits");
        // at most one wei lost per side per trader (4 floor divisions)
        assertLe(dust, 4, "dust is bounded rounding only");
        // fee is the snapshotted 2% of the pot
        assertEq(fee, (deposits * 200) / 10_000, "fee == 2% of pot");
    }

    /// LONG settles higher the higher the value lands: for v1 <= v2, an identical
    /// book pays the LONG side at least as much at v2 as at v1.
    function testFuzz_longPayoutMonotoneInValue(uint256 stake, int256 v1, int256 v2) public {
        stake = _bound(stake, MIN, MAX);
        // keep both values inside the band and ordered
        uint256 a = uint256(_bound(uint256(v1), 0, 1000));
        uint256 b = uint256(_bound(uint256(v2), 0, 1000));
        if (a > b) (a, b) = (b, a);
        int256 lo = LOWER + int256(a);
        int256 hi = LOWER + int256(b);

        uint256 longAtLo = _longPayoutAt(keccak256("mono-lo"), stake, lo);
        uint256 longAtHi = _longPayoutAt(keccak256("mono-hi"), stake, hi);
        assertLe(longAtLo, longAtHi, "higher value never pays long less");
    }

    // build an identical balanced book (stake LONG vs stake SHORT), settle at
    // `value`, and return what the sole LONG trader is paid.
    function _longPayoutAt(bytes32 salt, uint256 stake, int256 value) internal returns (uint256) {
        bytes32 id = _market(salt);
        _take(id, la, ScalarMarketEngine.Side.Long, stake);
        _take(id, sa, ScalarMarketEngine.Side.Short, stake);
        vm.warp(block.timestamp + 2 days);
        oracle.set(id, value);
        engine.resolve(id);
        return _claim(id, la);
    }
}
