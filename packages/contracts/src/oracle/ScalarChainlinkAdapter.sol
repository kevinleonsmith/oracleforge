// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IScalarOracleAdapter} from "../interfaces/IScalarOracleAdapter.sol";
import {AggregatorV3Interface} from "./AggregatorV3Interface.sol";

/// @title ScalarChainlinkAdapter
/// @notice Scalar-market oracle: reports a Chainlink feed's raw answer (rescaled
///         to the market's unit) for the ScalarMarketEngine to clamp into its
///         band. The binary ChainlinkOracleAdapter answers a yes/no comparison;
///         this one answers "what is the value?".
///
/// Encoding of `oracleParams` (abi.encode):
///   (address feed, address fallbackFeed, uint8 targetDecimals, uint64 maxStale)
///
/// Design decisions (see docs/SECURITY-REVIEW.md, O1-O4 — shared with the binary
/// adapter, plus a scalar-specific improvement):
///   - Reuses the same health logic: a feed answer of <= 0 (uninitialized or a
///     malfunctioning/negative feed) or a zero timestamp is treated as unhealthy
///     and is never reported (fail-safe: the engine stays Open). Targets
///     non-negative feeds; a signed-feed scalar adapter is a separate concern.
///   - `maxStale == 0` disables the staleness check (foot-gun, by design).
///   - The answer is **rescaled** from the feed's native decimals to
///     `targetDecimals`, so a market's [lower, upper] band is expressed in a
///     chosen unit (e.g. whole dollars, not 8-decimal feed units). Because each
///     feed is rescaled independently to the same target, a fallback with
///     *different* decimals than the primary is handled correctly — so unlike the
///     binary adapter (O2) no decimal-match is required.
contract ScalarChainlinkAdapter is IScalarOracleAdapter {
    struct Config {
        AggregatorV3Interface feed;
        AggregatorV3Interface fallbackFeed;
        uint8 targetDecimals;
        uint64 maxStale; // seconds; 0 disables the staleness check
        bool set;
    }

    /// @notice Upper bound on targetDecimals, to keep rescaling well within int256.
    uint8 public constant MAX_TARGET_DECIMALS = 36;

    address public engine;
    address public immutable deployer;
    mapping(bytes32 => Config) public configs;

    event EngineSet(address indexed engine);

    modifier onlyEngine() {
        require(msg.sender == engine, "SORACLE: not engine");
        _;
    }

    constructor() {
        deployer = msg.sender;
    }

    /// @notice One-time binding of the ScalarMarketEngine (breaks the deploy
    ///         cycle, as with the binary adapter).
    function initEngine(address _engine) external {
        require(msg.sender == deployer, "SORACLE: not deployer");
        require(engine == address(0), "SORACLE: engine set");
        require(_engine != address(0), "SORACLE: zero");
        engine = _engine;
        emit EngineSet(_engine);
    }

    /// @inheritdoc IScalarOracleAdapter
    function configure(bytes32 marketId, bytes calldata params) external onlyEngine {
        (address feed, address fallbackFeed, uint8 targetDecimals, uint64 maxStale) =
            abi.decode(params, (address, address, uint8, uint64));
        require(feed != address(0), "SORACLE: feed zero");
        require(targetDecimals <= MAX_TARGET_DECIMALS, "SORACLE: decimals");
        configs[marketId] = Config({
            feed: AggregatorV3Interface(feed),
            fallbackFeed: AggregatorV3Interface(fallbackFeed),
            targetDecimals: targetDecimals,
            maxStale: maxStale,
            set: true
        });
    }

    /// @inheritdoc IScalarOracleAdapter
    function latestValue(bytes32 marketId) external view returns (bool ready, int256 value) {
        Config memory c = configs[marketId];
        if (!c.set) return (false, 0);

        (bool ok, int256 raw, uint8 dec) = _read(c.feed, c.maxStale);
        if (!ok && address(c.fallbackFeed) != address(0)) {
            (ok, raw, dec) = _read(c.fallbackFeed, c.maxStale);
        }
        if (!ok) return (false, 0); // no healthy feed yet — stay not-ready

        return (true, _rescale(raw, dec, c.targetDecimals));
    }

    function _read(AggregatorV3Interface feed, uint64 maxStale)
        internal
        view
        returns (bool ok, int256 answer, uint8 dec)
    {
        if (address(feed) == address(0)) return (false, 0, 0);
        (, int256 a,, uint256 updatedAt,) = feed.latestRoundData();
        if (a <= 0 || updatedAt == 0) return (false, 0, 0);
        if (maxStale != 0 && block.timestamp > updatedAt + maxStale) return (false, 0, 0);
        // A feed reporting pathological decimals would make _rescale's 10**(from-to)
        // overflow (revert) or wrap the int256 cast negative. Treat it as unhealthy
        // and fail safe (stay not-ready / try the fallback), consistent with every
        // other health failure — never let a bad feed DoS or corrupt resolution (O5).
        uint8 dec = feed.decimals();
        if (dec > MAX_TARGET_DECIMALS) return (false, 0, 0);
        return (true, a, dec);
    }

    /// @dev Rescale a feed answer from `from` decimals to `to` decimals. Scaling
    ///      down floors (loses sub-unit precision); scaling up is exact.
    function _rescale(int256 a, uint8 from, uint8 to) internal pure returns (int256) {
        if (from == to) return a;
        if (from > to) {
            return a / int256(10 ** (uint256(from) - uint256(to)));
        }
        return a * int256(10 ** (uint256(to) - uint256(from)));
    }
}
