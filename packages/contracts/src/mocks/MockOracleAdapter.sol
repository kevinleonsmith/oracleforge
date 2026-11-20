// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IOracleAdapter} from "../interfaces/IOracleAdapter.sol";

/// @notice A settable oracle adapter for local devnets and tests. Lets a harness
///         drive a market to a chosen outcome directly, decoupled from Chainlink
///         feed mechanics (which `ChainlinkOracleAdapter` + `MockAggregator`
///         cover). Not for production use.
contract MockOracleAdapter is IOracleAdapter {
    mapping(bytes32 => Outcome) public outcomeOf;

    /// @dev No-op: the engine calls this at market creation; the mock needs no params.
    function configure(bytes32, bytes calldata) external {}

    /// @notice Force a market's resolution outcome.
    function setOutcome(bytes32 marketId, Outcome o) external {
        outcomeOf[marketId] = o;
    }

    /// @inheritdoc IOracleAdapter
    function resolve(bytes32 marketId) external view returns (Outcome) {
        return outcomeOf[marketId]; // defaults to Pending (0) until set
    }
}
