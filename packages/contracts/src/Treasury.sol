// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ITreasury} from "./interfaces/ITreasury.sol";
import {IERC20} from "./interfaces/IERC20.sol";

/// @title Treasury
/// @notice Holds protocol fees and funds named reserve buckets. `allocate` is
///         gated to the governor (a Gnosis Chain governance module / Safe in
///         production). Buckets are bytes32 tags, e.g. keccak256("AKASH_GPU").
/// @dev Accounting model: every token the treasury is responsible for is tracked
///      twice — once per bucket in `reserves`, and once in aggregate in
///      `totalReserved`. The two always agree (sum of a token's buckets equals
///      its `totalReserved`), and `totalReserved[token] <= balanceOf(treasury)`
///      for any standard ERC-20. The gap, if any, is tokens sent directly to the
///      treasury without `collectFee`; `sweep` reconciles those into a bucket.
contract Treasury is ITreasury {
    address public governor;
    /// @notice Nominated next governor; must call acceptGovernor() to take the
    ///         role (two-step), so a mistyped handover can't strand the treasury.
    address public pendingGovernor;

    /// bucket => token => reserved balance (accounting view; funds are commingled)
    mapping(bytes32 => mapping(address => uint256)) public reserves;
    /// token => total across all buckets (== sum of reserves[*][token])
    mapping(address => uint256) public totalReserved;

    /// @notice Bucket unassigned fees and swept donations land in.
    bytes32 public constant OPERATIONS = keccak256("OPERATIONS");

    event GovernorUpdated(address indexed governor);
    event GovernorTransferStarted(address indexed currentGovernor, address indexed pendingGovernor);
    event Reallocated(bytes32 indexed from, bytes32 indexed to, address indexed token, uint256 amount);
    event Swept(address indexed token, bytes32 indexed bucket, uint256 amount);

    modifier onlyGovernor() {
        require(msg.sender == governor, "TREASURY: not governor");
        _;
    }

    constructor(address _governor) {
        require(_governor != address(0), "TREASURY: governor zero");
        governor = _governor;
        emit GovernorUpdated(_governor);
    }

    // --------------------------------------------------------------- governance

    /// @notice Begin a two-step governor handover. The role does not move until
    ///         the nominee calls acceptGovernor(); address(0) cancels a pending
    ///         nomination.
    function transferGovernor(address newGovernor) external onlyGovernor {
        pendingGovernor = newGovernor;
        emit GovernorTransferStarted(governor, newGovernor);
    }

    /// @notice Accept a pending governor nomination. Callable only by the nominee.
    function acceptGovernor() external {
        require(msg.sender == pendingGovernor, "TREASURY: not pending governor");
        governor = pendingGovernor;
        pendingGovernor = address(0);
        emit GovernorUpdated(governor);
    }

    // -------------------------------------------------------------------- funds

    /// @inheritdoc ITreasury
    function collectFee(address token, uint256 amount) external {
        require(IERC20(token).transferFrom(msg.sender, address(this), amount), "TREASURY: pull");
        // Unassigned fees land in the OPERATIONS bucket until governance reallocates.
        reserves[OPERATIONS][token] += amount;
        totalReserved[token] += amount;
        emit FeeReceived(token, msg.sender, amount);
    }

    /// @notice Governance moves funds between accounting buckets (totals unchanged).
    function reallocate(bytes32 from, bytes32 to, address token, uint256 amount)
        external
        onlyGovernor
    {
        require(reserves[from][token] >= amount, "TREASURY: bucket");
        reserves[from][token] -= amount;
        reserves[to][token] += amount;
        emit Reallocated(from, to, token, amount);
    }

    /// @inheritdoc ITreasury
    function allocate(bytes32 bucket, address token, address to, uint256 amount)
        external
        onlyGovernor
    {
        require(reserves[bucket][token] >= amount, "TREASURY: bucket");
        // Effects before interaction (CEI): debit both the bucket and the total,
        // then transfer out.
        reserves[bucket][token] -= amount;
        totalReserved[token] -= amount;
        require(IERC20(token).transfer(to, amount), "TREASURY: send");
        emit Allocated(bucket, to, amount);
    }

    /// @notice Reconcile tokens sent to the treasury outside `collectFee` (direct
    ///         transfers / donations) by crediting the untracked balance into a
    ///         bucket. Without this, such funds would be unrecoverable — every
    ///         bucket would read zero for them and `allocate` could never move
    ///         them out.
    /// @return amount the previously-untracked balance now credited to `bucket`.
    function sweep(address token, bytes32 bucket) external onlyGovernor returns (uint256 amount) {
        uint256 bal = IERC20(token).balanceOf(address(this));
        uint256 tracked = totalReserved[token];
        require(bal > tracked, "TREASURY: nothing to sweep");
        amount = bal - tracked;
        reserves[bucket][token] += amount;
        totalReserved[token] = bal;
        emit Swept(token, bucket, amount);
    }
}
