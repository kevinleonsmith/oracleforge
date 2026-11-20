// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title ITreasury
/// @notice Protocol treasury that receives market fees and funds reserves
///         (protocol-owned liquidity, Akash GPU reserve, incentives, disputes).
interface ITreasury {
    event FeeReceived(address indexed token, address indexed from, uint256 amount);
    event Allocated(bytes32 indexed bucket, address indexed to, uint256 amount);

    /// @notice Pull `amount` of `token` from msg.sender into the treasury.
    /// @dev Caller must have approved the treasury first.
    function collectFee(address token, uint256 amount) external;

    /// @notice Governance-gated transfer out of a named reserve bucket.
    function allocate(bytes32 bucket, address token, address to, uint256 amount) external;
}
