// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {ScalarMarketEngine} from "../src/ScalarMarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockScalarOracle} from "../src/mocks/MockScalarOracle.sol";

/// @notice Optimistic-resolution coverage for the scalar engine: a nonzero
///         challenge window makes resolve() only *propose* a settlement value;
///         it must survive the window (or an admin arbitration of a bonded
///         dispute) before finalize() opens claims. Mirrors MarketEngineDispute.
contract ScalarMarketEngineDisputeTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    MockScalarOracle oracle;
    ScalarMarketEngine engine;

    address admin = address(0xA11CE);
    address longT = address(0x1040);
    address shortT = address(0x5401);
    address charlie = address(0xC4); // challenger

    int256 constant LOWER = 100;
    int256 constant UPPER = 200;
    uint64 constant WINDOW = 1 hours;
    uint256 constant BOND = 100e18;
    bytes32 id;

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(admin);
        oracle = new MockScalarOracle();
        engine = new ScalarMarketEngine(address(collateral), address(oracle), address(treasury), admin);

        vm.prank(admin);
        engine.setChallengeWindow(WINDOW);
        vm.prank(admin);
        engine.setDisputeBond(BOND);

        address[3] memory who = [longT, shortT, charlie];
        for (uint256 i; i < 3; i++) {
            collateral.mint(who[i], 10_000e18);
            vm.prank(who[i]);
            collateral.approve(address(engine), type(uint256).max);
        }

        vm.prank(admin);
        id = engine.createMarket(keccak256("range?"), uint64(block.timestamp + 7 days), LOWER, UPPER, "");
        vm.prank(longT);
        engine.takePosition(id, ScalarMarketEngine.Side.Long, 600e18);
        vm.prank(shortT);
        engine.takePosition(id, ScalarMarketEngine.Side.Short, 400e18);
    }

    // warp past close and propose `value` (status -> Closed under a window)
    function _propose(int256 value) internal {
        vm.warp(block.timestamp + 8 days);
        oracle.set(id, value);
        engine.resolve(id);
    }

    function _claim(address who) internal returns (uint256) {
        vm.prank(who);
        return engine.claim(id);
    }

    function test_window_blocksClaimUntilFinalized() public {
        _propose(150);
        // proposed, not resolved: status Closed, claims blocked
        assertEq(uint256(uint8(engine.getMarket(id).status)), 1, "closed/proposed");
        vm.prank(longT);
        vm.expectRevert(bytes("SCALAR: unresolved"));
        engine.claim(id);
        // can't finalize before the window elapses
        vm.expectRevert(bytes("SCALAR: window open"));
        engine.finalize(id);

        vm.warp(block.timestamp + WINDOW + 1);
        engine.finalize(id);
        assertEq(uint256(uint8(engine.getMarket(id).status)), 2, "resolved");
        // f=0.5 -> 490/490
        assertEq(_claim(longT), 490e18, "long payout after finalize");
        assertEq(_claim(shortT), 490e18, "short payout after finalize");
    }

    function test_dispute_rejected_forfeitsBond_valueStands() public {
        _propose(150);
        vm.prank(charlie);
        engine.dispute(id);
        assertEq(engine.challengerOf(id), charlie, "challenger recorded");

        // admin rejects the challenge: bond forfeited, proposed value (150) stands
        vm.prank(admin);
        engine.arbitrate(id, 150, false);
        assertEq(engine.challengerOf(id), address(0), "cleared");
        assertTrue(engine.getMarket(id).settledValue == 150, "value stands");
        // treasury holds the 2% fee (20) plus the forfeited bond (100)
        assertEq(collateral.balanceOf(address(treasury)), 20e18 + BOND, "fee + forfeited bond");
        assertEq(_claim(longT), 490e18, "long payout at 150");
    }

    function test_dispute_upheld_refundsBond_appliesAdminValue() public {
        _propose(150);
        uint256 charlieBefore = collateral.balanceOf(charlie);
        vm.prank(charlie);
        engine.dispute(id);

        // admin upholds and overrides to 120 -> f = (120-100)/100 = 0.2
        vm.prank(admin);
        engine.arbitrate(id, 120, true);
        assertTrue(engine.getMarket(id).settledValue == 120, "admin value applied");
        assertEq(collateral.balanceOf(charlie), charlieBefore, "bond refunded in full");
        // distributable 980: long 196, short 784
        assertEq(_claim(longT), 196e18, "long at f=0.2");
        assertEq(_claim(shortT), 784e18, "short at f=0.2");
        // only the fee is in the treasury (bond was refunded)
        assertEq(collateral.balanceOf(address(treasury)), 20e18, "fee only");
    }

    function test_dispute_afterWindow_reverts() public {
        _propose(150);
        vm.warp(block.timestamp + WINDOW + 1);
        vm.prank(charlie);
        vm.expectRevert(bytes("SCALAR: window closed"));
        engine.dispute(id);
    }

    function test_disputesDisabled_whenBondZero() public {
        vm.prank(admin);
        engine.setDisputeBond(0);
        _propose(150);
        vm.prank(charlie);
        vm.expectRevert(bytes("SCALAR: disputes off"));
        engine.dispute(id);
    }

    function test_arbitrate_guards() public {
        _propose(150);
        // no dispute open yet
        vm.prank(admin);
        vm.expectRevert(bytes("SCALAR: no dispute"));
        engine.arbitrate(id, 150, false);
        // only admin
        vm.prank(charlie);
        engine.dispute(id);
        vm.prank(charlie);
        vm.expectRevert(bytes("SCALAR: not admin"));
        engine.arbitrate(id, 150, true);
    }

    function test_oneSidedVoid_bypassesWindow() public {
        // a fresh one-sided market voids immediately even with a window set
        vm.prank(admin);
        bytes32 solo = engine.createMarket(keccak256("solo"), uint64(block.timestamp + 1 days), LOWER, UPPER, "");
        vm.prank(longT);
        engine.takePosition(solo, ScalarMarketEngine.Side.Long, 300e18); // no shorts
        vm.warp(block.timestamp + 2 days);
        oracle.set(solo, 150);
        engine.resolve(solo);
        assertEq(uint256(uint8(engine.getMarket(solo).status)), 3, "void, not proposed");
        vm.prank(longT);
        assertEq(engine.claim(solo), 300e18, "principal refunded");
    }
}
