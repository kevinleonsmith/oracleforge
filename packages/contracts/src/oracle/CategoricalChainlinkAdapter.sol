// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ICategoricalOracleAdapter} from "../interfaces/ICategoricalOracleAdapter.sol";
import {AggregatorV3Interface} from "./AggregatorV3Interface.sol";

/// @title CategoricalChainlinkAdapter
/// @notice Categorical-market oracle: reports the *winning outcome index* a feed
///         names (e.g. a Chainlink Functions consumer that posts the result of a
///         match, election or award as an integer). Where the binary adapter
///         answers a yes/no comparison and the scalar adapter answers a numeric
///         value, this one answers "which outcome won?".
///
/// Encoding of `oracleParams` (abi.encode):
///   (address feed, address fallbackFeed, uint64 maxStale)
///
/// Design decisions (shared health posture with the binary/scalar adapters, with
/// a categorical-specific twist on the zero case):
///   - A zero timestamp (uninitialized/malfunctioning feed) is unhealthy and is
///     never reported — fail-safe, the engine stays Open.
///   - A **negative** answer is unhealthy (a feed error sentinel); but unlike the
///     scalar adapter, `0` is a *valid* outcome index (the first outcome), so only
///     `< 0` is rejected, never `== 0`.
///   - `maxStale == 0` disables the staleness check (foot-gun, by design).
///   - An answer that overflows `uint8` is out of any valid outcome range, so it
///     is reported as the invalid sentinel `type(uint8).max`, which the engine
///     treats as a void (refund) rather than a truncated index. The engine makes
///     the final range check against the market's own `outcomeCount`.
///   - No decimal rescaling: an outcome index is a plain integer, not a price.
contract CategoricalChainlinkAdapter is ICategoricalOracleAdapter {
    struct Config {
        AggregatorV3Interface feed;
        AggregatorV3Interface fallbackFeed;
        uint64 maxStale; // seconds; 0 disables the staleness check
        bool set;
    }

    /// @notice Reported when a healthy answer is out of the uint8 outcome range;
    ///         the engine treats it as invalid and voids (refunds).
    uint8 public constant INVALID_OUTCOME = type(uint8).max;

    address public engine;
    address public immutable deployer;
    mapping(bytes32 => Config) public configs;

    event EngineSet(address indexed engine);

    modifier onlyEngine() {
        require(msg.sender == engine, "CORACLE: not engine");
        _;
    }

    constructor() {
        deployer = msg.sender;
    }

    /// @notice One-time binding of the CategoricalMarketEngine (breaks the deploy
    ///         cycle, as with the binary/scalar adapters).
    function initEngine(address _engine) external {
        require(msg.sender == deployer, "CORACLE: not deployer");
        require(engine == address(0), "CORACLE: engine set");
        require(_engine != address(0), "CORACLE: zero");
        engine = _engine;
        emit EngineSet(_engine);
    }

    /// @inheritdoc ICategoricalOracleAdapter
    function configure(bytes32 marketId, bytes calldata params) external onlyEngine {
        (address feed, address fallbackFeed, uint64 maxStale) =
            abi.decode(params, (address, address, uint64));
        require(feed != address(0), "CORACLE: feed zero");
        configs[marketId] = Config({
            feed: AggregatorV3Interface(feed),
            fallbackFeed: AggregatorV3Interface(fallbackFeed),
            maxStale: maxStale,
            set: true
        });
    }

    /// @inheritdoc ICategoricalOracleAdapter
    function latestOutcome(bytes32 marketId) external view returns (bool ready, uint8 outcome) {
        Config memory c = configs[marketId];
        if (!c.set) return (false, 0);

        (bool ok, int256 raw) = _read(c.feed, c.maxStale);
        if (!ok && address(c.fallbackFeed) != address(0)) {
            (ok, raw) = _read(c.fallbackFeed, c.maxStale);
        }
        if (!ok) return (false, 0); // no healthy feed yet — stay not-ready

        // A valid index fits in uint8; anything larger is out of range -> void.
        if (uint256(raw) > uint256(INVALID_OUTCOME)) return (true, INVALID_OUTCOME);
        return (true, uint8(uint256(raw)));
    }

    function _read(AggregatorV3Interface feed, uint64 maxStale)
        internal
        view
        returns (bool ok, int256 answer)
    {
        if (address(feed) == address(0)) return (false, 0);
        (, int256 a,, uint256 updatedAt,) = feed.latestRoundData();
        // 0 is a valid outcome index, so only a negative answer is unhealthy here.
        if (a < 0 || updatedAt == 0) return (false, 0);
        if (maxStale != 0 && block.timestamp > updatedAt + maxStale) return (false, 0);
        return (true, a);
    }
}
