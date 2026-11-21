// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ICategoricalOracleAdapter} from "./interfaces/ICategoricalOracleAdapter.sol";
import {ITreasury} from "./interfaces/ITreasury.sol";
import {IERC20} from "./interfaces/IERC20.sol";

/// @title CategoricalMarketEngine
/// @notice Parimutuel *categorical* (N-outcome) prediction market. A market has
///         `outcomeCount` mutually-exclusive outcomes (0..N-1); traders stake on
///         one. At settlement the oracle names the single winning outcome, and
///         the winning pool splits the entire losing pot — minus the protocol
///         fee — pro-rata to stake:
///
///           winningPool = pools[winner]
///           losingPool  = totalPot - winningPool
///           fee         = losingPool * feeBps / 10_000      (snapshotted)
///           payout(a)   = stake(a) + stake(a) * (losingPool - fee) / winningPool
///
///         This is the binary engine generalized from 2 outcomes to N: a binary
///         market is exactly the N=2 case (Yes/No). Winner-take-all, unlike the
///         scalar engine's continuum.
/// @dev MVP scaffold, not audited. Same hardened posture as MarketEngine
///      (two-step admin, zero-address guards, fee snapshotted at creation, and a
///      no-winner void that refunds every principal). The optimistic dispute
///      window is a later addition, as it was for the scalar engine.
contract CategoricalMarketEngine {
    enum Status {
        Open, // 0
        Resolved, // 1
        Invalid // 2 — voided; principals refunded
    }

    struct Market {
        bytes32 questionHash;
        uint64 createdAt;
        uint64 closeAt;
        uint8 outcomeCount; // N (2..MAX_OUTCOMES)
        uint16 feeBps; // snapshotted at creation
        Status status;
        uint8 winningOutcome; // set at resolve
        uint256 losingPoolNet; // distributable losing pool after fee (set at resolve)
        uint256[] pools; // length N: staked total per outcome
    }

    /// @notice Hard cap on outcomes so the resolve/refund loops stay bounded. The
    ///         invalid sentinel type(uint8).max is always above this, so it can
    ///         never collide with a valid outcome index.
    uint8 public constant MAX_OUTCOMES = 64;

    IERC20 public immutable collateral;
    ICategoricalOracleAdapter public immutable oracle;
    ITreasury public immutable treasury;

    /// @notice Default protocol fee (bps) applied to markets at creation; each
    ///         market snapshots this, so changing it never alters an open market.
    uint16 public feeBps = 200; // 2.0%

    mapping(address => bool) public isRelayer;
    address public admin;
    /// @notice Nominated next admin (two-step handover).
    address public pendingAdmin;

    mapping(bytes32 => Market) internal _markets;
    // marketId => account => outcome => staked amount
    mapping(bytes32 => mapping(address => mapping(uint8 => uint256))) public stakeOf;
    mapping(bytes32 => mapping(address => bool)) public claimed;

    event MarketCreated(bytes32 indexed marketId, bytes32 questionHash, uint64 closeAt, uint8 outcomeCount);
    event PositionTaken(bytes32 indexed marketId, address indexed account, uint8 outcome, uint256 amount);
    event MarketResolved(bytes32 indexed marketId, uint8 winningOutcome, uint256 fee);
    event MarketVoided(bytes32 indexed marketId);
    event Claimed(bytes32 indexed marketId, address indexed account, uint256 payout);
    event RelayerUpdated(address indexed relayer, bool allowed);
    event FeeUpdated(uint16 feeBps);
    event AdminTransferStarted(address indexed currentAdmin, address indexed pendingAdmin);
    event AdminTransferred(address indexed previousAdmin, address indexed newAdmin);

    modifier onlyAdmin() {
        require(msg.sender == admin, "CAT: not admin");
        _;
    }

    modifier onlyRelayer() {
        require(isRelayer[msg.sender], "CAT: not relayer");
        _;
    }

    constructor(address _collateral, address _oracle, address _treasury, address _admin) {
        require(_collateral != address(0), "CAT: collateral zero");
        require(_oracle != address(0), "CAT: oracle zero");
        require(_treasury != address(0), "CAT: treasury zero");
        require(_admin != address(0), "CAT: admin zero");
        collateral = IERC20(_collateral);
        oracle = ICategoricalOracleAdapter(_oracle);
        treasury = ITreasury(_treasury);
        admin = _admin;
        isRelayer[_admin] = true;
    }

    // --------------------------------------------------------------------- admin

    function transferAdmin(address newAdmin) external onlyAdmin {
        pendingAdmin = newAdmin;
        emit AdminTransferStarted(admin, newAdmin);
    }

    function acceptAdmin() external {
        require(msg.sender == pendingAdmin, "CAT: not pending admin");
        address previous = admin;
        admin = pendingAdmin;
        pendingAdmin = address(0);
        emit AdminTransferred(previous, admin);
    }

    function setRelayer(address relayer, bool allowed) external onlyAdmin {
        isRelayer[relayer] = allowed;
        emit RelayerUpdated(relayer, allowed);
    }

    function setFeeBps(uint16 _feeBps) external onlyAdmin {
        require(_feeBps <= 1000, "CAT: fee too high"); // max 10%
        feeBps = _feeBps;
        emit FeeUpdated(_feeBps);
    }

    // ------------------------------------------------------------------- markets

    function createMarket(
        bytes32 questionHash,
        uint64 closeAt,
        uint8 outcomeCount,
        bytes calldata oracleParams
    ) external onlyRelayer returns (bytes32 marketId) {
        require(closeAt > block.timestamp, "CAT: closeAt past");
        require(outcomeCount >= 2 && outcomeCount <= MAX_OUTCOMES, "CAT: outcomes");

        marketId = keccak256(abi.encodePacked(questionHash, closeAt, block.chainid));
        require(_markets[marketId].createdAt == 0, "CAT: exists");

        // Build in storage so the dynamic pools array is initialized to length N.
        Market storage m = _markets[marketId];
        m.questionHash = questionHash;
        m.createdAt = uint64(block.timestamp);
        m.closeAt = closeAt;
        m.outcomeCount = outcomeCount;
        m.feeBps = feeBps; // snapshot
        m.status = Status.Open;
        for (uint256 i; i < outcomeCount; i++) {
            m.pools.push(0);
        }

        oracle.configure(marketId, oracleParams);
        emit MarketCreated(marketId, questionHash, closeAt, outcomeCount);
    }

    function takePosition(bytes32 marketId, uint8 outcome, uint256 amount) external {
        Market storage m = _markets[marketId];
        require(m.createdAt != 0, "CAT: no market");
        require(m.status == Status.Open, "CAT: not open");
        require(block.timestamp < m.closeAt, "CAT: closed");
        require(outcome < m.outcomeCount, "CAT: outcome range");
        require(amount > 0, "CAT: zero");

        require(collateral.transferFrom(msg.sender, address(this), amount), "CAT: pull");

        m.pools[outcome] += amount;
        stakeOf[marketId][msg.sender][outcome] += amount;

        emit PositionTaken(marketId, msg.sender, outcome, amount);
    }

    /// @notice Permissionless: read the oracle and settle a closed market. An
    ///         out-of-range outcome (the invalid sentinel) or a winning pool with
    ///         no stake voids the market (every principal refundable).
    function resolve(bytes32 marketId) external {
        Market storage m = _markets[marketId];
        require(m.createdAt != 0, "CAT: no market");
        require(m.status == Status.Open, "CAT: not open");
        require(block.timestamp >= m.closeAt, "CAT: not closed");

        (bool ready, uint8 outcome) = oracle.latestOutcome(marketId);
        require(ready, "CAT: oracle pending");

        // Out-of-range outcome (incl. the invalid sentinel) -> void & refund.
        if (outcome >= m.outcomeCount) {
            m.status = Status.Invalid;
            emit MarketVoided(marketId);
            return;
        }

        uint256 winningPool = m.pools[outcome];
        // No stake on the winning outcome -> push: void so everyone is refunded.
        // (claim needs winningPool > 0 as the pro-rata denominator, and the losing
        // pot would otherwise be stranded forever.)
        if (winningPool == 0) {
            m.status = Status.Invalid;
            emit MarketVoided(marketId);
            return;
        }

        uint256 totalPot;
        for (uint256 i; i < m.outcomeCount; i++) {
            totalPot += m.pools[i];
        }
        uint256 losingPool = totalPot - winningPool;
        uint256 fee = (losingPool * m.feeBps) / 10_000;

        m.winningOutcome = outcome;
        m.losingPoolNet = losingPool - fee; // distributable to winners
        m.status = Status.Resolved;

        if (fee > 0) {
            collateral.approve(address(treasury), fee);
            treasury.collectFee(address(collateral), fee);
        }
        emit MarketResolved(marketId, outcome, fee);
    }

    function claim(bytes32 marketId) external returns (uint256 payout) {
        Market storage m = _markets[marketId];
        require(!claimed[marketId][msg.sender], "CAT: claimed");

        if (m.status == Status.Invalid) {
            uint256 refund;
            for (uint8 i; i < m.outcomeCount; i++) {
                refund += stakeOf[marketId][msg.sender][i];
            }
            require(refund > 0, "CAT: nothing");
            claimed[marketId][msg.sender] = true;
            require(collateral.transfer(msg.sender, refund), "CAT: refund");
            emit Claimed(marketId, msg.sender, refund);
            return refund;
        }

        require(m.status == Status.Resolved, "CAT: unresolved");
        uint256 stake = stakeOf[marketId][msg.sender][m.winningOutcome];
        require(stake > 0, "CAT: no winnings");

        uint256 winningPool = m.pools[m.winningOutcome];
        // principal + pro-rata share of the (fee-reduced) losing pool
        payout = stake + (stake * m.losingPoolNet) / winningPool;

        claimed[marketId][msg.sender] = true;
        require(collateral.transfer(msg.sender, payout), "CAT: payout");
        emit Claimed(marketId, msg.sender, payout);
    }

    function getMarket(bytes32 marketId) external view returns (Market memory) {
        return _markets[marketId];
    }

    /// @notice The staked total for one outcome (convenience over getMarket().pools).
    function poolOf(bytes32 marketId, uint8 outcome) external view returns (uint256) {
        return _markets[marketId].pools[outcome];
    }
}
