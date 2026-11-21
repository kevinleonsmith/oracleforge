// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {ForgeGovernor} from "../src/ForgeGovernor.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";

/// @notice End-to-end: token holders take control of the Treasury through the
///         governor and then govern it. The deploy script deliberately does *not*
///         force the handover (it only deploys the governor); this proves the
///         intended path actually works — a proposal calls `treasury.acceptGovernor`
///         to complete the two-step transfer, after which the Treasury obeys only
///         the governor, and a second proposal moves funds via `allocate`. This is
///         the "governance governs the protocol" guarantee the standalone governor
///         and deploy tests don't cover together.
contract ForgeGovernorHandoverTest is MiniTest {
    MockERC20 forge; // governance token
    MockERC20 collateral; // treasury-held asset
    Treasury treasury;
    ForgeGovernor gov;

    address deployer = address(this); // initial Treasury governor
    address alice = address(0xA1); // 1000 FORGE — proposer/voter
    address bob = address(0xB0); // 600 FORGE — voter
    address grantee = address(0x6412); // receives an allocation

    uint64 constant PERIOD = 1 days;
    uint256 constant THRESHOLD = 100e18;
    uint256 constant QUORUM = 1000e18;
    bytes32 constant OPS = keccak256("OPERATIONS");

    function setUp() public {
        forge = new MockERC20("Forge", "FORGE", 18);
        forge.mint(alice, 1000e18);
        forge.mint(bob, 600e18);

        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(deployer); // deployer is the initial governor
        gov = new ForgeGovernor(address(forge), PERIOD, THRESHOLD, QUORUM, deployer);

        // Fund the treasury's OPERATIONS bucket with 10k USDC (as fees would).
        collateral.mint(address(this), 10_000e18);
        collateral.approve(address(treasury), 10_000e18);
        treasury.collectFee(address(collateral), 10_000e18);
    }

    /// Drive a proposal to a passing, executed state.
    function _passAndExecute(address target, bytes memory data) internal returns (uint256 id) {
        vm.prank(alice);
        id = gov.propose(target, data, "governance action");
        vm.prank(alice);
        gov.castVote(id, true); // 1000 FORGE FOR -> meets quorum, majority
        vm.prank(bob);
        gov.castVote(id, true); // 600 more
        vm.warp(block.timestamp + PERIOD + 1);
        assertEq(uint8(gov.state(id)), uint8(ForgeGovernor.State.Succeeded), "succeeded");
        gov.execute(id);
    }

    function test_governanceTakesOverTreasuryThenAllocates() public {
        // 1) the current governor (deployer) nominates the ForgeGovernor.
        treasury.transferGovernor(address(gov));
        assertEq(treasury.pendingGovernor(), address(gov), "governor nominated");
        assertEq(treasury.governor(), deployer, "not yet transferred");

        // 2) a proposal ratifies the handover by calling acceptGovernor() AS the
        //    governor contract (msg.sender == pendingGovernor).
        _passAndExecute(address(treasury), abi.encodeWithSelector(Treasury.acceptGovernor.selector));
        assertEq(treasury.governor(), address(gov), "treasury now governed by the governor");
        assertEq(treasury.pendingGovernor(), address(0), "nomination cleared");

        // 3) the deployer can no longer govern the treasury directly.
        vm.expectRevert(bytes("TREASURY: not governor"));
        treasury.allocate(OPS, address(collateral), grantee, 1e18);

        // 4) but a governance proposal can: allocate 2500 USDC to the grantee.
        uint256 before = collateral.balanceOf(grantee);
        _passAndExecute(
            address(treasury),
            abi.encodeWithSelector(Treasury.allocate.selector, OPS, address(collateral), grantee, 2_500e18)
        );
        assertEq(collateral.balanceOf(grantee) - before, 2_500e18, "grantee funded by governance");
        assertEq(treasury.reserves(OPS, address(collateral)), 7_500e18, "OPS bucket debited");
    }

    /// A failing governed call bubbles up as a revert, so a bad proposal can't
    /// silently "succeed" — here an over-allocation beyond the bucket balance.
    function test_governedCallThatRevertsFailsExecution() public {
        treasury.transferGovernor(address(gov));
        _passAndExecute(address(treasury), abi.encodeWithSelector(Treasury.acceptGovernor.selector));

        vm.prank(alice);
        uint256 id = gov.propose(
            address(treasury),
            abi.encodeWithSelector(Treasury.allocate.selector, OPS, address(collateral), grantee, 1_000_000e18),
            "over-allocate"
        );
        vm.prank(alice);
        gov.castVote(id, true);
        vm.warp(block.timestamp + PERIOD + 1);
        vm.expectRevert(bytes("GOV: exec failed")); // the treasury's bucket check reverts
        gov.execute(id);
    }
}
