// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title IOracleAdapter
/// @notice Abstraction over the data source that resolves a market. Concrete
///         adapters wrap Chainlink price/data feeds, Chainlink Functions, or a
///         Cartesi-attested result. The MarketEngine never talks to a feed
///         directly — it asks an adapter whether a market's condition is met.
interface IOracleAdapter {
    /// @notice Resolution outcome for a market.
    /// Pending  — not yet resolvable (before close, or feed not ready)
    /// Yes / No — resolved binary outcome
    /// Invalid  — market voided; collateral is refunded pro-rata
    enum Outcome {
        Pending,
        Yes,
        No,
        Invalid
    }

    /// @notice Attempt to resolve a market by its id.
    /// @dev Must be deterministic and side-effect free (view) so Cartesi
    ///      fraud proofs can replay it. Returns Pending if not yet resolvable.
    function resolve(bytes32 marketId) external view returns (Outcome);

    /// @notice Register the oracle parameters for a market (feed id, threshold,
    ///         comparator). Called by the MarketEngine at market creation.
    function configure(bytes32 marketId, bytes calldata params) external;
}
