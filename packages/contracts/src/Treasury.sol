// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ITreasury} from "./interfaces/ITreasury.sol";
import {IERC20} from "./interfaces/IERC20.sol";

/// @title Treasury
/// @notice Holds protocol fees and funds named reserve buckets. `allocate` is
///         gated to the governor (a Gnosis Chain governance module / Safe in
///         production). Buckets are bytes32 tags, e.g. keccak256("AKASH_GPU").
contract Treasury is ITreasury {
    address public governor;

    /// bucket => token => reserved balance (accounting view; funds are commingled)
    mapping(bytes32 => mapping(address => uint256)) public reserves;

    event GovernorUpdated(address indexed governor);

    modifier onlyGovernor() {
        require(msg.sender == governor, "TREASURY: not governor");
        _;
    }

    constructor(address _governor) {
        governor = _governor;
        emit GovernorUpdated(_governor);
    }

    function setGovernor(address _governor) external onlyGovernor {
        governor = _governor;
        emit GovernorUpdated(_governor);
    }

    /// @inheritdoc ITreasury
    function collectFee(address token, uint256 amount) external {
        require(IERC20(token).transferFrom(msg.sender, address(this), amount), "TREASURY: pull");
        // Unassigned fees land in the OPERATIONS bucket until governance reallocates.
        reserves[keccak256("OPERATIONS")][token] += amount;
        emit FeeReceived(token, msg.sender, amount);
    }

    /// @notice Governance moves funds between accounting buckets.
    function reallocate(bytes32 from, bytes32 to, address token, uint256 amount)
        external
        onlyGovernor
    {
        require(reserves[from][token] >= amount, "TREASURY: bucket");
        reserves[from][token] -= amount;
        reserves[to][token] += amount;
    }

    /// @inheritdoc ITreasury
    function allocate(bytes32 bucket, address token, address to, uint256 amount)
        external
        onlyGovernor
    {
        require(reserves[bucket][token] >= amount, "TREASURY: bucket");
        reserves[bucket][token] -= amount;
        require(IERC20(token).transfer(to, amount), "TREASURY: send");
        emit Allocated(bucket, to, amount);
    }
}
