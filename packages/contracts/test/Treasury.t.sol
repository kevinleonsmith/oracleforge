// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";

/// @notice Focused review coverage for the Treasury: fee intake + bucket
///         accounting, governed allocation, two-step governor rotation (T1),
///         constructor zero-address guard (T2), and donation sweep (T3). Until
///         now the Treasury was only exercised indirectly through MarketEngine.
contract TreasuryTest is MiniTest {
    MockERC20 token;
    Treasury treasury;

    address gov = address(0x60F);
    address newGov = address(0x9E0);
    address stranger = address(0xBAD);
    address grantee = address(0x6AA);

    bytes32 constant OPS = keccak256("OPERATIONS");
    bytes32 constant GPU = keccak256("AKASH_GPU");

    function setUp() public {
        token = new MockERC20("USD Coin", "USDC", 6);
        treasury = new Treasury(gov);
        token.mint(address(this), 1_000_000e6);
    }

    // feed `amount` into the treasury via the real collectFee path
    function _fee(uint256 amount) internal {
        token.approve(address(treasury), amount);
        treasury.collectFee(address(token), amount);
    }

    // ------------------------------------------------------------- accounting

    function test_collectFee_creditsOperationsAndTotal() public {
        _fee(500e6);
        assertEq(treasury.reserves(OPS, address(token)), 500e6, "ops bucket");
        assertEq(treasury.totalReserved(address(token)), 500e6, "total tracked");
        assertEq(token.balanceOf(address(treasury)), 500e6, "held");
    }

    function test_allocate_debitsBucketTotalAndSends() public {
        _fee(500e6);
        vm.prank(gov);
        treasury.allocate(OPS, address(token), grantee, 200e6);
        assertEq(treasury.reserves(OPS, address(token)), 300e6, "bucket debited");
        assertEq(treasury.totalReserved(address(token)), 300e6, "total debited");
        assertEq(token.balanceOf(grantee), 200e6, "grantee paid");
        // invariant holds: total == bucket sum == balance (no stray funds)
        assertEq(treasury.totalReserved(address(token)), token.balanceOf(address(treasury)), "reconciled");
    }

    function test_allocate_onlyGovernor() public {
        _fee(100e6);
        vm.prank(stranger);
        vm.expectRevert(bytes("TREASURY: not governor"));
        treasury.allocate(OPS, address(token), grantee, 10e6);
    }

    function test_allocate_revertsOnOverBucket() public {
        _fee(100e6);
        vm.prank(gov);
        vm.expectRevert(bytes("TREASURY: bucket"));
        treasury.allocate(OPS, address(token), grantee, 101e6);
    }

    function test_reallocate_movesBetweenBuckets_totalUnchanged() public {
        _fee(500e6);
        vm.prank(gov);
        treasury.reallocate(OPS, GPU, address(token), 300e6);
        assertEq(treasury.reserves(OPS, address(token)), 200e6, "ops reduced");
        assertEq(treasury.reserves(GPU, address(token)), 300e6, "gpu funded");
        assertEq(treasury.totalReserved(address(token)), 500e6, "total unchanged");
    }

    function test_reallocate_onlyGovernor() public {
        _fee(100e6);
        vm.prank(stranger);
        vm.expectRevert(bytes("TREASURY: not governor"));
        treasury.reallocate(OPS, GPU, address(token), 10e6);
    }

    // ------------------------------------------------------- T1: governor swap

    function test_transferGovernor_isTwoStep() public {
        vm.prank(gov);
        treasury.transferGovernor(newGov);
        assertEq(treasury.governor(), gov, "unchanged until accepted");
        assertEq(treasury.pendingGovernor(), newGov, "nominee pending");

        vm.prank(newGov);
        treasury.acceptGovernor();
        assertEq(treasury.governor(), newGov, "rotated");
        assertEq(treasury.pendingGovernor(), address(0), "pending cleared");

        // new governor has the power; old one is locked out
        vm.prank(newGov);
        treasury.reallocate(OPS, GPU, address(token), 0);
        vm.prank(gov);
        vm.expectRevert(bytes("TREASURY: not governor"));
        treasury.reallocate(OPS, GPU, address(token), 0);
    }

    function test_onlyGovernor_canNominate() public {
        vm.prank(stranger);
        vm.expectRevert(bytes("TREASURY: not governor"));
        treasury.transferGovernor(stranger);
    }

    function test_onlyNominee_canAccept() public {
        vm.prank(gov);
        treasury.transferGovernor(newGov);
        vm.prank(stranger);
        vm.expectRevert(bytes("TREASURY: not pending governor"));
        treasury.acceptGovernor();
    }

    function test_nomination_canBeCancelled() public {
        vm.prank(gov);
        treasury.transferGovernor(newGov);
        vm.prank(gov);
        treasury.transferGovernor(address(0));
        vm.prank(newGov);
        vm.expectRevert(bytes("TREASURY: not pending governor"));
        treasury.acceptGovernor();
    }

    // ----------------------------------------------------- T2: zero-addr guard

    function test_constructor_rejectsZeroGovernor() public {
        vm.expectRevert(bytes("TREASURY: governor zero"));
        new Treasury(address(0));
    }

    // -------------------------------------------------------- T3: donation sweep

    function test_sweep_reconcilesDirectTransfers() public {
        _fee(100e6);
        // someone transfers straight to the treasury, bypassing collectFee
        require(token.transfer(address(treasury), 40e6), "seed");
        assertEq(treasury.totalReserved(address(token)), 100e6, "untracked before sweep");
        assertEq(token.balanceOf(address(treasury)), 140e6, "balance ahead of tracked");

        vm.prank(gov);
        uint256 swept = treasury.sweep(address(token), GPU);
        assertEq(swept, 40e6, "swept the gap");
        assertEq(treasury.reserves(GPU, address(token)), 40e6, "credited to bucket");
        assertEq(treasury.totalReserved(address(token)), 140e6, "now reconciled");
        // the swept funds are now allocatable
        vm.prank(gov);
        treasury.allocate(GPU, address(token), grantee, 40e6);
        assertEq(token.balanceOf(grantee), 40e6, "donation recovered");
    }

    function test_sweep_revertsWhenNothingUntracked() public {
        _fee(100e6);
        vm.prank(gov);
        vm.expectRevert(bytes("TREASURY: nothing to sweep"));
        treasury.sweep(address(token), OPS);
    }

    function test_sweep_onlyGovernor() public {
        require(token.transfer(address(treasury), 10e6), "seed");
        vm.prank(stranger);
        vm.expectRevert(bytes("TREASURY: not governor"));
        treasury.sweep(address(token), OPS);
    }
}
