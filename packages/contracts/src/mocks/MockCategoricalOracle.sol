// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ICategoricalOracleAdapter} from "../interfaces/ICategoricalOracleAdapter.sol";

/// @notice Settable categorical oracle for tests and local dev. `set` names the
///         winning outcome and makes it ready; `setInvalid` reports the
///         out-of-range sentinel (voids the market); `clear` marks it not-yet-ready.
contract MockCategoricalOracle is ICategoricalOracleAdapter {
    mapping(bytes32 => bool) public configured;
    mapping(bytes32 => bool) internal _ready;
    mapping(bytes32 => uint8) internal _outcome;

    function configure(bytes32 marketId, bytes calldata) external {
        configured[marketId] = true;
    }

    function set(bytes32 marketId, uint8 outcome) external {
        _outcome[marketId] = outcome;
        _ready[marketId] = true;
    }

    /// @notice Report the invalid sentinel (type(uint8).max), which the engine
    ///         treats as out of range -> void.
    function setInvalid(bytes32 marketId) external {
        _outcome[marketId] = type(uint8).max;
        _ready[marketId] = true;
    }

    function clear(bytes32 marketId) external {
        _ready[marketId] = false;
    }

    function latestOutcome(bytes32 marketId) external view returns (bool, uint8) {
        return (_ready[marketId], _outcome[marketId]);
    }
}
