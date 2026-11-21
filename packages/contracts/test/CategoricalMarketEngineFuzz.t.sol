// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {CategoricalMarketEngine} from "../src/CategoricalMarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockCategoricalOracle} from "../src/mocks/MockCategoricalOracle.sol";

/// @notice Property tests for categorical settlement: value is conserved across
///         any book (payouts + fee + dust == deposits) — proven both for a
///         two-winner 3-outcome book (so the dust bound is exercised) and for a
///         variable number of outcomes 2..8 with an arbitrary winning index.
contract CategoricalMarketEngineFuzzTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    MockCategoricalOracle oracle;
    CategoricalMarketEngine engine;

    address admin = address(0xA11CE);
    address alice = address(0xA1);
    address bob = address(0xB0);
    address carol = address(0xCA);
    address dave = address(0xDA);
    address staker = address(0x57);

    uint256 constant MIN = 1e15;
    uint256 constant MAX = 1e27;

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(admin);
        oracle = new MockCategoricalOracle();
        engine = new CategoricalMarketEngine(address(collateral), address(oracle), address(treasury), admin);

        address[5] memory who = [alice, bob, carol, dave, staker];
        for (uint256 i; i < 5; i++) {
            collateral.mint(who[i], 1e30);
            vm.prank(who[i]);
            collateral.approve(address(engine), type(uint256).max);
        }
    }

    function _market(bytes32 salt, uint8 n) internal returns (bytes32 id) {
        vm.prank(admin);
        id = engine.createMarket(salt, uint64(block.timestamp + 1 days), n, "");
    }

    function _take(bytes32 id, address who, uint8 outcome, uint256 amt) internal {
        vm.prank(who);
        engine.takePosition(id, outcome, amt);
    }

    function _claim(bytes32 id, address who) internal returns (uint256) {
        vm.prank(who);
        return engine.claim(id);
    }

    /// Two winners on a 3-outcome book: payouts + fee + dust == deposits, dust is
    /// bounded sub-wei rounding only (<= 2 floor divisions), and the fee is the
    /// snapshotted 2% of the losing pool.
    function testFuzz_conservesWithTwoWinners(uint256 a, uint256 b, uint256 c, uint256 d) public {
        a = _bound(a, MIN, MAX);
        b = _bound(b, MIN, MAX);
        c = _bound(c, MIN, MAX);
        d = _bound(d, MIN, MAX);

        bytes32 id = _market(keccak256("two-winners"), 3);
        _take(id, alice, 0, a);
        _take(id, bob, 0, b);
        _take(id, carol, 1, c);
        _take(id, dave, 2, d);

        vm.warp(block.timestamp + 2 days);
        oracle.set(id, 0); // outcome 0 wins
        engine.resolve(id);

        uint256 deposits = a + b + c + d;
        uint256 losing = c + d;
        uint256 fee = collateral.balanceOf(address(treasury));
        assertEq(fee, (losing * 200) / 10_000, "fee == 2% of losing pool");

        uint256 paid = _claim(id, alice) + _claim(id, bob);
        uint256 dust = collateral.balanceOf(address(engine));
        assertEq(paid + fee + dust, deposits, "payouts + fee + dust == deposits");
        assertLe(dust, 2, "dust is bounded rounding only (2 winners)");
    }

    /// Variable outcome count (2..8) with an arbitrary winning index: one staker
    /// funds every outcome, so the winner's pool is the whole winning stake and
    /// the entire losing pot (net of fee) returns to them. Conservation holds for
    /// any N and any winner — exercising the array sum/refund loops.
    function testFuzz_conservesForAnyOutcomeCount(uint256 nRaw, uint256 winRaw, uint256 base) public {
        uint8 n = uint8(_bound(nRaw, 2, 8));
        uint8 win = uint8(_bound(winRaw, 0, n - 1));
        base = _bound(base, MIN, MAX / 8);

        bytes32 id = _market(keccak256(abi.encodePacked("anyN", nRaw, winRaw)), n);

        uint256 deposits;
        uint256 winnerStake;
        for (uint8 i; i < n; i++) {
            uint256 amt = base + uint256(i) * MIN; // distinct, nonzero per outcome
            _take(id, staker, i, amt);
            deposits += amt;
            if (i == win) winnerStake = amt;
        }

        vm.warp(block.timestamp + 2 days);
        oracle.set(id, win);
        engine.resolve(id);

        uint256 losing = deposits - winnerStake;
        uint256 fee = collateral.balanceOf(address(treasury));
        assertEq(fee, (losing * 200) / 10_000, "fee == 2% of losing pool");

        uint256 paid = _claim(id, staker);
        uint256 dust = collateral.balanceOf(address(engine));
        assertEq(paid + fee + dust, deposits, "payouts + fee + dust == deposits");
        // single winner holding the whole winning pool => exact division, no dust
        assertEq(dust, 0, "no dust for a sole winner");
    }
}
