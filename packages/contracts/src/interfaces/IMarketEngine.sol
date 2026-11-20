// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title IMarketEngine
/// @notice Binary (YES/NO) prediction-market engine. Markets are created by the
///         AI market generator (via an authorized relayer), collateralized in a
///         single ERC-20, resolved through an IOracleAdapter, and settled with a
///         protocol fee routed to the treasury.
interface IMarketEngine {
    enum Side {
        No,
        Yes
    }

    enum Status {
        Open, // accepting positions
        Closed, // past close time, awaiting resolution
        Resolved, // outcome set, winners can claim
        Invalid // voided, everyone refunded
    }

    struct Market {
        bytes32 questionHash; // keccak256 of canonical question text (full text on Arweave/Tableland)
        uint64 createdAt;
        uint64 closeAt; // positions blocked after this time
        uint16 aiProbBps; // AI-initialized YES probability, basis points (0..10000)
        uint16 feeBps; // protocol fee snapshotted at creation (immutable for this market)
        Status status;
        uint8 outcome; // valid once Resolved: 1 = Yes, 0 = No
        uint256 yesPool; // collateral staked on YES
        uint256 noPool; // collateral staked on NO
    }

    event MarketCreated(
        bytes32 indexed marketId, bytes32 questionHash, uint64 closeAt, uint16 aiProbBps
    );
    event PositionTaken(bytes32 indexed marketId, address indexed account, Side side, uint256 amount);
    event MarketResolved(bytes32 indexed marketId, uint8 outcome, uint256 feePaid);
    event Claimed(bytes32 indexed marketId, address indexed account, uint256 payout);

    function createMarket(
        bytes32 questionHash,
        uint64 closeAt,
        uint16 aiProbBps,
        bytes calldata oracleParams
    ) external returns (bytes32 marketId);

    function takePosition(bytes32 marketId, Side side, uint256 amount) external;

    function resolve(bytes32 marketId) external;

    function claim(bytes32 marketId) external returns (uint256 payout);

    function getMarket(bytes32 marketId) external view returns (Market memory);
}
