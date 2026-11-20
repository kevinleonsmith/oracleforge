// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IScalarOracleAdapter} from "../interfaces/IScalarOracleAdapter.sol";

/// @notice Settable scalar oracle for tests and local dev. `set` makes a value
///         ready; `clear` marks it not-yet-resolvable again.
contract MockScalarOracle is IScalarOracleAdapter {
    mapping(bytes32 => bool) public configured;
    mapping(bytes32 => bool) internal _ready;
    mapping(bytes32 => int256) internal _value;

    function configure(bytes32 marketId, bytes calldata) external {
        configured[marketId] = true;
    }

    function set(bytes32 marketId, int256 value) external {
        _value[marketId] = value;
        _ready[marketId] = true;
    }

    function clear(bytes32 marketId) external {
        _ready[marketId] = false;
    }

    function latestValue(bytes32 marketId) external view returns (bool, int256) {
        return (_ready[marketId], _value[marketId]);
    }
}
