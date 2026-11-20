// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title IScalarOracleAdapter
/// @notice Oracle abstraction for scalar (range) markets. Unlike the binary
///         IOracleAdapter — which answers Yes/No/Invalid — a scalar adapter
///         reports a raw numeric value that the ScalarMarketEngine clamps into
///         the market's [lower, upper] band to settle LONG/SHORT proportionally.
interface IScalarOracleAdapter {
    /// @notice Register the oracle parameters for a scalar market at creation.
    function configure(bytes32 marketId, bytes calldata params) external;

    /// @notice Current settlement value for a market.
    /// @dev Must be deterministic and side-effect free (view). `ready` is false
    ///      when the feed is not yet resolvable (before close, stale, missing),
    ///      in which case `value` is meaningless and the engine stays Open.
    function latestValue(bytes32 marketId) external view returns (bool ready, int256 value);
}
