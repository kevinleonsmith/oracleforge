// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "./interfaces/IERC20.sol";

/// @title ForgeGovernor
/// @notice Minimal token-weighted on-chain governance over the protocol. A holder
///         with at least `proposalThreshold` FORGE may propose an arbitrary call
///         (e.g. `MarketEngine.setFeeBps`, `Treasury.allocate`, an admin rotation);
///         holders vote with weight equal to their FORGE balance; after the voting
///         period a proposal that cleared quorum with a FOR majority can be executed
///         by anyone, which performs the call.
/// @dev MVP scaffold, not audited. Hardened in the same style as the engines
///      (two-step admin, zero-address guards, checks-effects-interactions on
///      execute). Voting weight is read at vote time rather than from a snapshot,
///      so this MVP does not defend against flash-loan/borrow-to-vote; production
///      would use an ERC20Votes checkpointed token or a block-snapshot. Documented
///      here, not hidden.
contract ForgeGovernor {
    enum State {
        Pending, // 0 — before voting opens (not used: voting opens at creation)
        Active, // 1 — voting open
        Defeated, // 2 — window closed without quorum + FOR majority
        Succeeded, // 3 — window closed, quorum met, FOR > AGAINST
        Executed, // 4 — the call has been performed
        Canceled // 5 — withdrawn by proposer/admin before execution
    }

    struct Proposal {
        address proposer;
        address target;
        bytes data;
        uint64 startAt;
        uint64 endAt;
        uint256 forVotes;
        uint256 againstVotes;
        bool executed;
        bool canceled;
    }

    IERC20 public immutable token;

    /// @notice Seconds a proposal stays open for voting.
    uint64 public votingPeriod;
    /// @notice Minimum FORGE balance required to submit a proposal.
    uint256 public proposalThreshold;
    /// @notice Minimum FOR votes for a proposal to be able to pass.
    uint256 public quorumVotes;

    address public admin;
    address public pendingAdmin;

    uint256 public proposalCount;
    mapping(uint256 => Proposal) internal _proposals;
    mapping(uint256 => mapping(address => bool)) public hasVoted;

    event ProposalCreated(
        uint256 indexed id, address indexed proposer, address indexed target, uint64 endAt, string description
    );
    event VoteCast(uint256 indexed id, address indexed voter, bool support, uint256 weight);
    event ProposalExecuted(uint256 indexed id);
    event ProposalCanceled(uint256 indexed id);
    event VotingPeriodUpdated(uint64 votingPeriod);
    event ProposalThresholdUpdated(uint256 threshold);
    event QuorumUpdated(uint256 quorum);
    event AdminTransferStarted(address indexed currentAdmin, address indexed pendingAdmin);
    event AdminTransferred(address indexed previousAdmin, address indexed newAdmin);

    modifier onlyAdmin() {
        require(msg.sender == admin, "GOV: not admin");
        _;
    }

    constructor(
        address _token,
        uint64 _votingPeriod,
        uint256 _proposalThreshold,
        uint256 _quorumVotes,
        address _admin
    ) {
        require(_token != address(0), "GOV: token zero");
        require(_admin != address(0), "GOV: admin zero");
        require(_votingPeriod > 0, "GOV: period zero");
        token = IERC20(_token);
        votingPeriod = _votingPeriod;
        proposalThreshold = _proposalThreshold;
        quorumVotes = _quorumVotes;
        admin = _admin;
    }

    // --------------------------------------------------------------------- admin

    function transferAdmin(address newAdmin) external onlyAdmin {
        pendingAdmin = newAdmin;
        emit AdminTransferStarted(admin, newAdmin);
    }

    function acceptAdmin() external {
        require(msg.sender == pendingAdmin, "GOV: not pending admin");
        address previous = admin;
        admin = pendingAdmin;
        pendingAdmin = address(0);
        emit AdminTransferred(previous, admin);
    }

    function setVotingPeriod(uint64 _votingPeriod) external onlyAdmin {
        require(_votingPeriod > 0, "GOV: period zero");
        votingPeriod = _votingPeriod;
        emit VotingPeriodUpdated(_votingPeriod);
    }

    function setProposalThreshold(uint256 _threshold) external onlyAdmin {
        proposalThreshold = _threshold;
        emit ProposalThresholdUpdated(_threshold);
    }

    function setQuorumVotes(uint256 _quorum) external onlyAdmin {
        quorumVotes = _quorum;
        emit QuorumUpdated(_quorum);
    }

    // ----------------------------------------------------------------- proposals

    function propose(address target, bytes calldata data, string calldata description)
        external
        returns (uint256 id)
    {
        require(token.balanceOf(msg.sender) >= proposalThreshold, "GOV: below threshold");
        require(target != address(0), "GOV: target zero");

        id = ++proposalCount;
        Proposal storage p = _proposals[id];
        p.proposer = msg.sender;
        p.target = target;
        p.data = data;
        p.startAt = uint64(block.timestamp);
        p.endAt = uint64(block.timestamp) + votingPeriod;

        emit ProposalCreated(id, msg.sender, target, p.endAt, description);
    }

    /// @notice Vote on an active proposal; weight is the caller's current FORGE balance.
    function castVote(uint256 id, bool support) external {
        require(state(id) == State.Active, "GOV: not active");
        require(!hasVoted[id][msg.sender], "GOV: already voted");
        uint256 weight = token.balanceOf(msg.sender);
        require(weight > 0, "GOV: no voting weight");

        hasVoted[id][msg.sender] = true;
        Proposal storage p = _proposals[id];
        if (support) p.forVotes += weight;
        else p.againstVotes += weight;

        emit VoteCast(id, msg.sender, support, weight);
    }

    /// @notice Execute a succeeded proposal's call. Permissionless once it passes.
    function execute(uint256 id) external returns (bytes memory) {
        require(state(id) == State.Succeeded, "GOV: not succeeded");
        Proposal storage p = _proposals[id];
        p.executed = true; // effects before interaction (CEI): a reentrant execute
            // re-reads state() as Executed and reverts.
        (bool ok, bytes memory ret) = p.target.call(p.data);
        require(ok, "GOV: exec failed");
        emit ProposalExecuted(id);
        return ret;
    }

    /// @notice Withdraw a proposal before it executes (proposer or admin).
    function cancel(uint256 id) external {
        State s = state(id);
        require(s != State.Executed && s != State.Canceled, "GOV: cannot cancel");
        Proposal storage p = _proposals[id];
        require(msg.sender == p.proposer || msg.sender == admin, "GOV: not canceler");
        p.canceled = true;
        emit ProposalCanceled(id);
    }

    // --------------------------------------------------------------------- views

    function state(uint256 id) public view returns (State) {
        require(id != 0 && id <= proposalCount, "GOV: unknown proposal");
        Proposal storage p = _proposals[id];
        if (p.canceled) return State.Canceled;
        if (p.executed) return State.Executed;
        if (block.timestamp < p.startAt) return State.Pending;
        if (block.timestamp <= p.endAt) return State.Active;
        // voting window has closed
        if (p.forVotes >= quorumVotes && p.forVotes > p.againstVotes) return State.Succeeded;
        return State.Defeated;
    }

    function getProposal(uint256 id) external view returns (Proposal memory) {
        return _proposals[id];
    }
}
