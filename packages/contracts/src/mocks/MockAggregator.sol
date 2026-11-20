// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AggregatorV3Interface} from "../oracle/AggregatorV3Interface.sol";

/// @notice Settable Chainlink-style feed for tests and local dev.
contract MockAggregator is AggregatorV3Interface {
    uint8 public decimals;
    string public description;
    int256 internal _answer;
    uint256 internal _updatedAt;
    uint80 internal _round;

    constructor(uint8 _decimals, string memory _description) {
        decimals = _decimals;
        description = _description;
        _updatedAt = block.timestamp;
    }

    function set(int256 answer) external {
        _answer = answer;
        _updatedAt = block.timestamp;
        _round++;
    }

    /// @notice Set an answer with an explicit (possibly stale) timestamp.
    function setWithTime(int256 answer, uint256 updatedAt) external {
        _answer = answer;
        _updatedAt = updatedAt;
        _round++;
    }

    function latestRoundData()
        external
        view
        returns (uint80, int256, uint256, uint256, uint80)
    {
        return (_round, _answer, _updatedAt, _updatedAt, _round);
    }
}
