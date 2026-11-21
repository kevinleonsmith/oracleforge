// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {ForgeGovernor} from "../src/ForgeGovernor.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";

/// A target the governor is authorized to drive: `setValue` is gated to the gov.
contract MockGoverned {
    address public gov;
    uint256 public value;

    constructor(address _gov) {
        gov = _gov;
    }

    function setValue(uint256 v) external {
        require(msg.sender == gov, "MG: not gov");
        value = v;
    }
}

/// A target whose call always reverts, to prove a failed execution reverts the governor.
contract MockReverter {
    function boom() external pure {
        revert("boom");
    }
}

contract ForgeGovernorTest is MiniTest {
    MockERC20 token;
    ForgeGovernor gov;
    MockGoverned governed;

    address admin = address(0xA11CE);
    address alice = address(0xA1); // 1000
    address bob = address(0xB0); // 500
    address carol = address(0xC0); // 300
    address whale = address(0x413A1E); // 2000
    address pauper = address(0xDEAD); // 0

    uint64 constant PERIOD = 1 days;
    uint256 constant THRESHOLD = 100e18;
    uint256 constant QUORUM = 1000e18;

    function setUp() public {
        token = new MockERC20("Forge", "FORGE", 18);
        token.mint(alice, 1000e18);
        token.mint(bob, 500e18);
        token.mint(carol, 300e18);
        token.mint(whale, 2000e18);
        gov = new ForgeGovernor(address(token), PERIOD, THRESHOLD, QUORUM, admin);
        governed = new MockGoverned(address(gov));
    }

    // --- helpers ----------------------------------------------------------
    function _propose(address who, uint256 v) internal returns (uint256 id) {
        bytes memory data = abi.encodeWithSelector(MockGoverned.setValue.selector, v);
        vm.prank(who);
        id = gov.propose(address(governed), data, "set the value");
    }

    function _vote(address who, uint256 id, bool support) internal {
        vm.prank(who);
        gov.castVote(id, support);
    }

    function _endVoting() internal {
        vm.warp(block.timestamp + PERIOD + 1);
    }

    // --- propose ----------------------------------------------------------

    function test_propose_belowThreshold_reverts() public {
        bytes memory data = abi.encodeWithSelector(MockGoverned.setValue.selector, uint256(1));
        vm.prank(pauper); // 0 balance < threshold
        vm.expectRevert(bytes("GOV: below threshold"));
        gov.propose(address(governed), data, "nope");
    }

    function test_propose_zeroTarget_reverts() public {
        vm.prank(alice);
        vm.expectRevert(bytes("GOV: target zero"));
        gov.propose(address(0), "", "nope");
    }

    function test_propose_createsActiveProposal() public {
        uint256 id = _propose(alice, 42);
        assertEq(id, 1, "first id");
        assertEq(uint8(gov.state(id)), uint8(ForgeGovernor.State.Active), "state");
        assertEq(gov.getProposal(id).proposer, alice, "proposer");
    }

    // --- voting -----------------------------------------------------------

    function test_castVote_weightsByBalance_andSucceeds() public {
        uint256 id = _propose(alice, 42);
        _vote(alice, id, true); // 1000
        _vote(bob, id, true); // 500
        ForgeGovernor.Proposal memory p = gov.getProposal(id);
        assertEq(p.forVotes, 1500e18, "for votes");
        _endVoting();
        assertEq(uint8(gov.state(id)), uint8(ForgeGovernor.State.Succeeded), "state");
    }

    function test_doubleVote_reverts() public {
        uint256 id = _propose(alice, 42);
        _vote(alice, id, true);
        vm.prank(alice);
        vm.expectRevert(bytes("GOV: already voted"));
        gov.castVote(id, true);
    }

    function test_vote_withNoWeight_reverts() public {
        uint256 id = _propose(alice, 42);
        vm.prank(pauper);
        vm.expectRevert(bytes("GOV: no voting weight"));
        gov.castVote(id, true);
    }

    function test_vote_afterWindow_reverts() public {
        uint256 id = _propose(alice, 42);
        _endVoting();
        vm.prank(bob);
        vm.expectRevert(bytes("GOV: not active"));
        gov.castVote(id, true);
    }

    // --- outcomes ---------------------------------------------------------

    function test_defeated_whenQuorumNotMet() public {
        uint256 id = _propose(carol, 42);
        _vote(carol, id, true); // 300 < quorum 1000
        _endVoting();
        assertEq(uint8(gov.state(id)), uint8(ForgeGovernor.State.Defeated), "state");
    }

    function test_defeated_whenAgainstOutweighsFor() public {
        uint256 id = _propose(alice, 42);
        _vote(alice, id, true); // FOR 1000 (meets quorum)
        _vote(whale, id, false); // AGAINST 2000
        _endVoting();
        assertEq(uint8(gov.state(id)), uint8(ForgeGovernor.State.Defeated), "state");
    }

    // --- execute ----------------------------------------------------------

    function test_execute_runsTheGovernedCall() public {
        uint256 id = _propose(alice, 42);
        _vote(alice, id, true);
        _endVoting();
        gov.execute(id);
        assertEq(governed.value(), 42, "governed value set by execution");
        assertEq(uint8(gov.state(id)), uint8(ForgeGovernor.State.Executed), "state");
    }

    function test_execute_beforeSucceeded_reverts() public {
        uint256 id = _propose(alice, 42);
        _vote(alice, id, true);
        // still Active (window open)
        vm.expectRevert(bytes("GOV: not succeeded"));
        gov.execute(id);
    }

    function test_execute_twice_reverts() public {
        uint256 id = _propose(alice, 42);
        _vote(alice, id, true);
        _endVoting();
        gov.execute(id);
        vm.expectRevert(bytes("GOV: not succeeded")); // now Executed
        gov.execute(id);
    }

    function test_execute_revertsOnFailedCall() public {
        MockReverter rev = new MockReverter();
        bytes memory data = abi.encodeWithSelector(MockReverter.boom.selector);
        vm.prank(alice);
        uint256 id = gov.propose(address(rev), data, "will revert");
        _vote(alice, id, true);
        _endVoting();
        vm.expectRevert(bytes("GOV: exec failed"));
        gov.execute(id);
    }

    // --- cancel -----------------------------------------------------------

    function test_cancel_byProposer_blocksExecute() public {
        uint256 id = _propose(alice, 42);
        _vote(alice, id, true);
        vm.prank(alice);
        gov.cancel(id);
        assertEq(uint8(gov.state(id)), uint8(ForgeGovernor.State.Canceled), "state");
        _endVoting();
        vm.expectRevert(bytes("GOV: not succeeded"));
        gov.execute(id);
    }

    function test_cancel_byAdmin() public {
        uint256 id = _propose(alice, 42);
        vm.prank(admin);
        gov.cancel(id);
        assertEq(uint8(gov.state(id)), uint8(ForgeGovernor.State.Canceled), "state");
    }

    function test_cancel_byStranger_reverts() public {
        uint256 id = _propose(alice, 42);
        vm.prank(bob);
        vm.expectRevert(bytes("GOV: not canceler"));
        gov.cancel(id);
    }

    function test_cancel_afterExecute_reverts() public {
        uint256 id = _propose(alice, 42);
        _vote(alice, id, true);
        _endVoting();
        gov.execute(id);
        vm.prank(alice);
        vm.expectRevert(bytes("GOV: cannot cancel"));
        gov.cancel(id);
    }

    // --- admin & params ---------------------------------------------------

    function test_admin_twoStepRotation() public {
        vm.prank(admin);
        gov.transferAdmin(alice);
        assertEq(gov.admin(), admin, "not rotated until accepted");
        vm.prank(alice);
        gov.acceptAdmin();
        assertEq(gov.admin(), alice, "rotated");
    }

    function test_setParams_onlyAdmin() public {
        vm.prank(bob);
        vm.expectRevert(bytes("GOV: not admin"));
        gov.setQuorumVotes(1);

        vm.prank(admin);
        gov.setQuorumVotes(5e18);
        assertEq(gov.quorumVotes(), 5e18, "quorum set");
    }

    function test_constructor_guards() public {
        vm.expectRevert(bytes("GOV: token zero"));
        new ForgeGovernor(address(0), PERIOD, THRESHOLD, QUORUM, admin);
        vm.expectRevert(bytes("GOV: admin zero"));
        new ForgeGovernor(address(token), PERIOD, THRESHOLD, QUORUM, address(0));
        vm.expectRevert(bytes("GOV: period zero"));
        new ForgeGovernor(address(token), 0, THRESHOLD, QUORUM, admin);
    }

    function test_state_unknownProposal_reverts() public {
        vm.expectRevert(bytes("GOV: unknown proposal"));
        gov.state(999);
    }
}
