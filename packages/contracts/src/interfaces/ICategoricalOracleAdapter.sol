// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title ICategoricalOracleAdapter
/// @notice Oracle abstraction for categorical (N-outcome) markets. Where the
///         binary IOracleAdapter answers Yes/No/Invalid and the scalar
///         IScalarOracleAdapter answers a numeric value, a categorical adapter
///         names the single *winning outcome index* among the market's N
///         mutually-exclusive outcomes.
interface ICategoricalOracleAdapter {
    /// @notice Register the oracle parameters for a categorical market at creation.
    function configure(bytes32 marketId, bytes calldata params) external;

    /// @notice The winning outcome index for a market.
    /// @dev Must be deterministic and side-effect free (view). `ready` is false
    ///      when the result is not yet known (before close, feed missing), in
    ///      which case `outcome` is meaningless and the engine stays Open. An
    ///      `outcome` that is out of range for the market (>= outcomeCount, e.g.
    ///      the sentinel `type(uint8).max`) signals an **invalid/cancelled**
    ///      market: the engine voids and refunds every principal.
    function latestOutcome(bytes32 marketId) external view returns (bool ready, uint8 outcome);
}
