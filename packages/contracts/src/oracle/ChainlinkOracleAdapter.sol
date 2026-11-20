// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IOracleAdapter} from "../interfaces/IOracleAdapter.sol";
import {AggregatorV3Interface} from "./AggregatorV3Interface.sol";

/// @title ChainlinkOracleAdapter
/// @notice Resolves a market by comparing a Chainlink feed's answer against a
///         threshold with a comparator (>=, <=). Includes a staleness guard and
///         an optional fallback feed for redundancy.
///
/// Encoding of `oracleParams` (abi.encode):
///   (address feed, address fallbackFeed, int256 threshold, uint8 comparator, uint64 maxStale)
///     comparator: 0 => answer >= threshold is YES
///                 1 => answer <= threshold is YES
contract ChainlinkOracleAdapter is IOracleAdapter {
    struct Config {
        AggregatorV3Interface feed;
        AggregatorV3Interface fallbackFeed;
        int256 threshold;
        uint8 comparator;
        uint64 maxStale; // seconds; 0 disables the staleness check
        bool set;
    }

    address public engine;
    address public immutable deployer;
    mapping(bytes32 => Config) public configs;

    event EngineSet(address indexed engine);

    modifier onlyEngine() {
        require(msg.sender == engine, "ORACLE: not engine");
        _;
    }

    constructor() {
        deployer = msg.sender;
    }

    /// @notice One-time binding of the MarketEngine (breaks the deploy cycle:
    ///         the engine needs the oracle address at construction, so the
    ///         oracle is deployed first and bound to the engine afterward).
    function initEngine(address _engine) external {
        require(msg.sender == deployer, "ORACLE: not deployer");
        require(engine == address(0), "ORACLE: engine set");
        require(_engine != address(0), "ORACLE: zero");
        engine = _engine;
        emit EngineSet(_engine);
    }

    /// @inheritdoc IOracleAdapter
    function configure(bytes32 marketId, bytes calldata params) external onlyEngine {
        (
            address feed,
            address fallbackFeed,
            int256 threshold,
            uint8 comparator,
            uint64 maxStale
        ) = abi.decode(params, (address, address, int256, uint8, uint64));
        require(feed != address(0), "ORACLE: feed zero");
        require(comparator <= 1, "ORACLE: comparator");
        configs[marketId] = Config({
            feed: AggregatorV3Interface(feed),
            fallbackFeed: AggregatorV3Interface(fallbackFeed),
            threshold: threshold,
            comparator: comparator,
            maxStale: maxStale,
            set: true
        });
    }

    /// @inheritdoc IOracleAdapter
    function resolve(bytes32 marketId) external view returns (Outcome) {
        Config memory c = configs[marketId];
        if (!c.set) return Outcome.Pending;

        (bool ok, int256 answer) = _read(c.feed, c.maxStale);
        if (!ok && address(c.fallbackFeed) != address(0)) {
            (ok, answer) = _read(c.fallbackFeed, c.maxStale);
        }
        if (!ok) return Outcome.Pending; // no healthy feed yet — stay pending, don't void

        bool yes = c.comparator == 0 ? (answer >= c.threshold) : (answer <= c.threshold);
        return yes ? Outcome.Yes : Outcome.No;
    }

    function _read(AggregatorV3Interface feed, uint64 maxStale)
        internal
        view
        returns (bool ok, int256 answer)
    {
        if (address(feed) == address(0)) return (false, 0);
        (, int256 a,, uint256 updatedAt,) = feed.latestRoundData();
        if (a == 0 || updatedAt == 0) return (false, 0);
        if (maxStale != 0 && block.timestamp > updatedAt + maxStale) return (false, 0);
        return (true, a);
    }
}
