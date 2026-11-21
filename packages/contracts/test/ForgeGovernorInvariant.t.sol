// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {ForgeGovernor} from "../src/ForgeGovernor.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";

/// A benign target the governor can execute against.
contract GovTarget {
    uint256 public value;

    function setValue(uint256 v) external {
        value = v;
    }
}

/// @notice Drives random, interleaved governance actions — propose / vote /
///         advance-time / execute / cancel — across many proposals and a fixed set
///         of token holders, keeping ghost tallies of exactly what it voted. Where
///         the unit tests prove one proposal's lifecycle, these prove the
///         *accounting* holds across an arbitrary history: the on-chain FOR/AGAINST
///         tallies always equal the weights actually cast (no phantom votes, no
///         double counting, no inflation), and an executed proposal stays executed.
contract ForgeGovernorHandler is MiniTest {
    ForgeGovernor public immutable gov;
    MockERC20 public immutable token;
    GovTarget public immutable target;

    address[4] public actors = [address(0xA1), address(0xA2), address(0xB1), address(0xB2)];

    uint256[] public ids;
    // ghost: the weights this handler has cast per proposal, split by side.
    mapping(uint256 => uint256) public gFor;
    mapping(uint256 => uint256) public gAgainst;
    uint256[] public executedIds;

    constructor(ForgeGovernor _gov, MockERC20 _token, GovTarget _target) {
        gov = _gov;
        token = _token;
        target = _target;
    }

    function idCount() external view returns (uint256) {
        return ids.length;
    }

    function executedCount() external view returns (uint256) {
        return executedIds.length;
    }

    function _actor(uint256 seed) internal view returns (address) {
        return actors[_bound(seed, 0, 3)];
    }

    /// An actor above the proposal threshold opens a proposal to set a value.
    function propose(uint256 aSeed, uint256 v) external {
        address who = _actor(aSeed);
        if (token.balanceOf(who) < gov.proposalThreshold()) return;
        bytes memory data = abi.encodeWithSelector(GovTarget.setValue.selector, v);
        vm.prank(who);
        uint256 id = gov.propose(address(target), data, "set value");
        ids.push(id);
    }

    /// An actor votes on an active proposal; the ghost tally mirrors the on-chain one.
    function vote(uint256 mSeed, uint256 aSeed, bool support) external {
        if (ids.length == 0) return;
        uint256 id = ids[_bound(mSeed, 0, ids.length - 1)];
        if (gov.state(id) != ForgeGovernor.State.Active) return;
        address who = _actor(aSeed);
        if (gov.hasVoted(id, who)) return;
        uint256 w = token.balanceOf(who);
        if (w == 0) return;

        vm.prank(who);
        gov.castVote(id, support);
        if (support) gFor[id] += w;
        else gAgainst[id] += w;
    }

    /// Advance time so voting windows close and proposals can finalize.
    function advanceTime(uint256 seed) external {
        vm.warp(block.timestamp + _bound(seed, 1 hours, 2 days));
    }

    /// Execute a succeeded proposal (permissionless once it passes).
    function execute(uint256 mSeed) external {
        if (ids.length == 0) return;
        uint256 id = ids[_bound(mSeed, 0, ids.length - 1)];
        if (gov.state(id) != ForgeGovernor.State.Succeeded) return;
        gov.execute(id);
        executedIds.push(id);
    }

    /// Proposer or a stranger tries to cancel; only an authorized caller succeeds.
    function cancel(uint256 mSeed, uint256 aSeed) external {
        if (ids.length == 0) return;
        uint256 id = ids[_bound(mSeed, 0, ids.length - 1)];
        ForgeGovernor.State s = gov.state(id);
        if (s == ForgeGovernor.State.Executed || s == ForgeGovernor.State.Canceled) return;
        address who = _actor(aSeed);
        // only the proposer (or admin) may cancel; a stranger reverts, caught here.
        vm.prank(who);
        try gov.cancel(id) {} catch {}
    }
}

/// @notice Stateful invariant suite for ForgeGovernor's vote accounting.
contract ForgeGovernorInvariantTest is MiniTest {
    MockERC20 token;
    ForgeGovernor gov;
    GovTarget target;
    ForgeGovernorHandler handler;

    address admin = address(0xA11CE);

    function setUp() public {
        token = new MockERC20("Forge", "FORGE", 18);
        token.mint(address(0xA1), 1000e18);
        token.mint(address(0xA2), 700e18);
        token.mint(address(0xB1), 500e18);
        token.mint(address(0xB2), 300e18);
        // period long enough that votes and a window-close both get exercised
        gov = new ForgeGovernor(address(token), 1 days, 100e18, 800e18, admin);
        target = new GovTarget();
        handler = new ForgeGovernorHandler(gov, token, target);
    }

    function targetContracts() public view returns (address[] memory addrs) {
        addrs = new address[](1);
        addrs[0] = address(handler);
    }

    /// Exact accounting: for every proposal, the on-chain FOR/AGAINST tallies equal
    /// precisely the weights the handler cast — so there are no phantom votes, no
    /// double counting (hasVoted blocks re-votes), and no weight inflation.
    function invariant_talliesEqualVotesCast() public view {
        uint256 n = handler.idCount();
        for (uint256 i; i < n; i++) {
            uint256 id = handler.ids(i);
            ForgeGovernor.Proposal memory p = gov.getProposal(id);
            assertEq(p.forVotes, handler.gFor(id), "forVotes == cast FOR weight");
            assertEq(p.againstVotes, handler.gAgainst(id), "againstVotes == cast AGAINST weight");
        }
    }

    /// Total votes on any proposal can never exceed the token supply (a corollary of
    /// exact accounting + fixed balances, asserted directly for clarity).
    function invariant_tallyWithinSupply() public view {
        uint256 supply = token.totalSupply();
        uint256 n = handler.idCount();
        for (uint256 i; i < n; i++) {
            ForgeGovernor.Proposal memory p = gov.getProposal(handler.ids(i));
            assertLe(p.forVotes + p.againstVotes, supply, "tally <= supply");
        }
    }

    /// Execution is terminal: a proposal the handler executed stays in the Executed
    /// state forever (it can never be re-executed or revert back).
    function invariant_executedStaysExecuted() public view {
        uint256 n = handler.executedCount();
        for (uint256 i; i < n; i++) {
            assertEq(
                uint8(gov.state(handler.executedIds(i))),
                uint8(ForgeGovernor.State.Executed),
                "executed proposal stays executed"
            );
        }
    }
}
