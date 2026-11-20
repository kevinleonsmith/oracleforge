// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IScalarOracleAdapter} from "./interfaces/IScalarOracleAdapter.sol";
import {ITreasury} from "./interfaces/ITreasury.sol";
import {IERC20} from "./interfaces/IERC20.sol";

/// @title ScalarMarketEngine
/// @notice Parimutuel *scalar* (range) prediction market. A market defines a band
///         [lower, upper]; traders take LONG or SHORT. At settlement the oracle's
///         value `v` is clamped into the band and the pot (minus a protocol fee)
///         is split by where `v` landed:
///
///           f = (clamp(v) - lower) / (upper - lower)   in [0, 1]
///           LONG side receives  f * distributable
///           SHORT side receives (1 - f) * distributable
///
///         and each trader takes their pro-rata share of their side's payout. So
///         LONG pays out more the higher `v` settles, SHORT the lower — a
///         continuous outcome, unlike the binary engine's winner-take-all.
/// @dev MVP scaffold, not audited. Same hardened posture as MarketEngine
///      (two-step admin, zero-address guards, fee snapshotted at creation,
///      no-winner/one-sided void). v1 settles atomically — no dispute window yet.
contract ScalarMarketEngine {
    enum Side {
        Short, // 0
        Long // 1
    }

    enum Status {
        Open, // 0
        Resolved, // 1
        Invalid // 2 — voided; principals refunded
    }

    struct Market {
        bytes32 questionHash;
        uint64 createdAt;
        uint64 closeAt;
        int256 lower;
        int256 upper;
        uint16 feeBps; // snapshotted at creation
        Status status;
        int256 settledValue; // clamped settlement value (set at resolve)
        uint256 longPool;
        uint256 shortPool;
    }

    IERC20 public immutable collateral;
    IScalarOracleAdapter public immutable oracle;
    ITreasury public immutable treasury;

    /// @notice Default protocol fee (bps) applied to markets at creation; each
    ///         market snapshots this, so changing it never alters an open market.
    uint16 public feeBps = 200; // 2.0%

    mapping(address => bool) public isRelayer;
    address public admin;
    /// @notice Nominated next admin (two-step handover).
    address public pendingAdmin;

    mapping(bytes32 => Market) internal _markets;
    // marketId => account => side => staked amount
    mapping(bytes32 => mapping(address => mapping(Side => uint256))) public stakeOf;
    mapping(bytes32 => mapping(address => bool)) public claimed;

    event MarketCreated(bytes32 indexed marketId, bytes32 questionHash, uint64 closeAt, int256 lower, int256 upper);
    event PositionTaken(bytes32 indexed marketId, address indexed account, Side side, uint256 amount);
    event MarketResolved(bytes32 indexed marketId, int256 settledValue, uint256 fee);
    event MarketVoided(bytes32 indexed marketId);
    event Claimed(bytes32 indexed marketId, address indexed account, uint256 payout);
    event RelayerUpdated(address indexed relayer, bool allowed);
    event FeeUpdated(uint16 feeBps);
    event AdminTransferStarted(address indexed currentAdmin, address indexed pendingAdmin);
    event AdminTransferred(address indexed previousAdmin, address indexed newAdmin);

    modifier onlyAdmin() {
        require(msg.sender == admin, "SCALAR: not admin");
        _;
    }

    modifier onlyRelayer() {
        require(isRelayer[msg.sender], "SCALAR: not relayer");
        _;
    }

    constructor(address _collateral, address _oracle, address _treasury, address _admin) {
        require(_collateral != address(0), "SCALAR: collateral zero");
        require(_oracle != address(0), "SCALAR: oracle zero");
        require(_treasury != address(0), "SCALAR: treasury zero");
        require(_admin != address(0), "SCALAR: admin zero");
        collateral = IERC20(_collateral);
        oracle = IScalarOracleAdapter(_oracle);
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
        require(msg.sender == pendingAdmin, "SCALAR: not pending admin");
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
        require(_feeBps <= 1000, "SCALAR: fee too high"); // max 10%
        feeBps = _feeBps;
        emit FeeUpdated(_feeBps);
    }

    // ------------------------------------------------------------------- markets

    function createMarket(
        bytes32 questionHash,
        uint64 closeAt,
        int256 lower,
        int256 upper,
        bytes calldata oracleParams
    ) external onlyRelayer returns (bytes32 marketId) {
        require(closeAt > block.timestamp, "SCALAR: closeAt past");
        require(upper > lower, "SCALAR: band");

        marketId = keccak256(abi.encodePacked(questionHash, closeAt, block.chainid));
        require(_markets[marketId].createdAt == 0, "SCALAR: exists");

        _markets[marketId] = Market({
            questionHash: questionHash,
            createdAt: uint64(block.timestamp),
            closeAt: closeAt,
            lower: lower,
            upper: upper,
            feeBps: feeBps,
            status: Status.Open,
            settledValue: 0,
            longPool: 0,
            shortPool: 0
        });

        oracle.configure(marketId, oracleParams);
        emit MarketCreated(marketId, questionHash, closeAt, lower, upper);
    }

    function takePosition(bytes32 marketId, Side side, uint256 amount) external {
        Market storage m = _markets[marketId];
        require(m.createdAt != 0, "SCALAR: no market");
        require(m.status == Status.Open, "SCALAR: not open");
        require(block.timestamp < m.closeAt, "SCALAR: closed");
        require(amount > 0, "SCALAR: zero");

        require(collateral.transferFrom(msg.sender, address(this), amount), "SCALAR: pull");

        if (side == Side.Long) m.longPool += amount;
        else m.shortPool += amount;
        stakeOf[marketId][msg.sender][side] += amount;

        emit PositionTaken(marketId, msg.sender, side, amount);
    }

    /// @notice Permissionless: settle a closed market from the oracle's value.
    function resolve(bytes32 marketId) external {
        Market storage m = _markets[marketId];
        require(m.createdAt != 0, "SCALAR: no market");
        require(m.status == Status.Open, "SCALAR: not open");
        require(block.timestamp >= m.closeAt, "SCALAR: not closed");

        (bool ready, int256 value) = oracle.latestValue(marketId);
        require(ready, "SCALAR: oracle pending");

        // A one-sided book has no counterparty to pay the other side, and a
        // clamped value would strand the empty side's share. Void (refund both),
        // the same push handling as the binary engine's no-winner case.
        if (m.longPool == 0 || m.shortPool == 0) {
            m.status = Status.Invalid;
            emit MarketVoided(marketId);
            return;
        }

        // Clamp into the band and store the settlement value.
        int256 cv = value < m.lower ? m.lower : (value > m.upper ? m.upper : value);
        m.settledValue = cv;
        m.status = Status.Resolved;

        // Skim the fee from the whole pot (both sides contribute), at the rate
        // snapshotted when the market opened.
        uint256 pot = m.longPool + m.shortPool;
        uint256 fee = (pot * m.feeBps) / 10_000;
        if (fee > 0) {
            collateral.approve(address(treasury), fee);
            treasury.collectFee(address(collateral), fee);
        }
        emit MarketResolved(marketId, cv, fee);
    }

    /// @notice LONG/SHORT payout pools after the fee, derived purely from the
    ///         market's stored fields (so claim never needs extra storage).
    function _payoutPools(Market memory m)
        internal
        pure
        returns (uint256 longPayout, uint256 shortPayout)
    {
        uint256 pot = m.longPool + m.shortPool;
        uint256 fee = (pot * m.feeBps) / 10_000;
        uint256 distributable = pot - fee;

        // cv is clamped into [lower, upper] at resolve, so these are non-negative
        // and den > 0 (createMarket requires upper > lower).
        uint256 num = uint256(m.settledValue - m.lower);
        uint256 den = uint256(m.upper - m.lower);

        longPayout = (distributable * num) / den;
        shortPayout = distributable - longPayout; // remainder, no dust lost here
    }

    function claim(bytes32 marketId) external returns (uint256 payout) {
        Market storage m = _markets[marketId];
        require(!claimed[marketId][msg.sender], "SCALAR: claimed");

        if (m.status == Status.Invalid) {
            uint256 refund = stakeOf[marketId][msg.sender][Side.Long]
                + stakeOf[marketId][msg.sender][Side.Short];
            require(refund > 0, "SCALAR: nothing");
            claimed[marketId][msg.sender] = true;
            require(collateral.transfer(msg.sender, refund), "SCALAR: refund");
            emit Claimed(marketId, msg.sender, refund);
            return refund;
        }

        require(m.status == Status.Resolved, "SCALAR: unresolved");
        uint256 longStake = stakeOf[marketId][msg.sender][Side.Long];
        uint256 shortStake = stakeOf[marketId][msg.sender][Side.Short];
        require(longStake + shortStake > 0, "SCALAR: no stake");

        (uint256 longPayout, uint256 shortPayout) = _payoutPools(m);
        // both pools are > 0 for a Resolved market (else it voided)
        payout = (longPayout * longStake) / m.longPool + (shortPayout * shortStake) / m.shortPool;

        claimed[marketId][msg.sender] = true;
        if (payout > 0) {
            require(collateral.transfer(msg.sender, payout), "SCALAR: payout");
        }
        emit Claimed(marketId, msg.sender, payout);
    }

    function getMarket(bytes32 marketId) external view returns (Market memory) {
        return _markets[marketId];
    }
}
