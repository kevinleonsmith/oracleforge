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
///      (two-step admin, zero-address guards, fee snapshotted at creation, a
///      no-winner void that refunds every principal, and an opt-in optimistic
///      dispute window: propose -> challenge -> finalize, with a bonded dispute
///      and admin arbitration; a zero challengeWindow keeps atomic settlement).
contract CategoricalMarketEngine {
    enum Status {
        Open, // 0
        Closed, // 1 — winning outcome proposed, awaiting finalization (dispute window)
        Resolved, // 2
        Invalid // 3 — voided; principals refunded
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

    // --- optimistic resolution + dispute window ---
    /// @notice Seconds a proposed winning outcome can be challenged before it
    ///         finalizes. 0 (the default) means resolve() finalizes immediately,
    ///         so the window is strictly opt-in and v1 behavior is preserved.
    uint64 public challengeWindow;
    /// @notice Collateral a challenger must bond to dispute. 0 disables disputes.
    uint256 public disputeBond;

    mapping(bytes32 => uint8) public proposedOutcome; // winning index proposed at resolve()
    mapping(bytes32 => uint64) public proposedAt; // timestamp the outcome was proposed
    mapping(bytes32 => address) public challengerOf; // nonzero while under dispute
    mapping(bytes32 => uint256) public bondOf; // exact bond posted for an open dispute

    event MarketCreated(bytes32 indexed marketId, bytes32 questionHash, uint64 closeAt, uint8 outcomeCount);
    event PositionTaken(bytes32 indexed marketId, address indexed account, uint8 outcome, uint256 amount);
    event ResolutionProposed(bytes32 indexed marketId, uint8 outcome, uint64 at);
    event MarketResolved(bytes32 indexed marketId, uint8 winningOutcome, uint256 fee);
    event MarketVoided(bytes32 indexed marketId);
    event Claimed(bytes32 indexed marketId, address indexed account, uint256 payout);
    event RelayerUpdated(address indexed relayer, bool allowed);
    event FeeUpdated(uint16 feeBps);
    event ChallengeWindowUpdated(uint64 window);
    event DisputeBondUpdated(uint256 bond);
    event Disputed(bytes32 indexed marketId, address indexed challenger, uint256 bond);
    event DisputeResolved(bytes32 indexed marketId, address indexed challenger, bool upheld);
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

    function setChallengeWindow(uint64 _window) external onlyAdmin {
        challengeWindow = _window;
        emit ChallengeWindowUpdated(_window);
    }

    function setDisputeBond(uint256 _bond) external onlyAdmin {
        disputeBond = _bond;
        emit DisputeBondUpdated(_bond);
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

    /// @notice Permissionless: read the oracle and *propose* a winning outcome for
    ///         a closed market. With a nonzero challengeWindow the proposal must
    ///         survive the window (or an admin arbitration of a dispute) before
    ///         finalize() settles; with a zero window it settles atomically. The
    ///         void decisions (out-of-range/invalid index, or a winning pool with
    ///         no stake) depend on the *final* outcome, so they are made at
    ///         finalization — a dispute could change the outcome to a funded one.
    function resolve(bytes32 marketId) external {
        Market storage m = _markets[marketId];
        require(m.createdAt != 0, "CAT: no market");
        require(m.status == Status.Open, "CAT: not open");
        require(block.timestamp >= m.closeAt, "CAT: not closed");

        (bool ready, uint8 outcome) = oracle.latestOutcome(marketId);
        require(ready, "CAT: oracle pending");

        proposedOutcome[marketId] = outcome;
        proposedAt[marketId] = uint64(block.timestamp);
        m.status = Status.Closed; // "proposed, awaiting finalization"
        emit ResolutionProposed(marketId, outcome, uint64(block.timestamp));

        // Fast path: no window => settle atomically (Open -> Resolved/Invalid).
        if (challengeWindow == 0) _finalize(marketId);
    }

    /// @notice Lock in a proposed outcome once its challenge window has elapsed and
    ///         no dispute is open. Permissionless, like resolve().
    function finalize(bytes32 marketId) external {
        require(_markets[marketId].status == Status.Closed, "CAT: not proposed");
        require(challengerOf[marketId] == address(0), "CAT: disputed");
        require(block.timestamp >= proposedAt[marketId] + challengeWindow, "CAT: window open");
        _finalize(marketId);
    }

    /// @notice Challenge a proposed outcome within its window by posting a bond.
    ///         Freezes finalization until the admin arbitrates. A rejected
    ///         challenge forfeits the bond to the treasury; an upheld one refunds it.
    function dispute(bytes32 marketId) external {
        require(_markets[marketId].status == Status.Closed, "CAT: not proposed");
        require(challengerOf[marketId] == address(0), "CAT: already disputed");
        require(disputeBond > 0, "CAT: disputes off");
        require(block.timestamp < proposedAt[marketId] + challengeWindow, "CAT: window closed");
        require(collateral.transferFrom(msg.sender, address(this), disputeBond), "CAT: bond");
        challengerOf[marketId] = msg.sender;
        bondOf[marketId] = disputeBond; // snapshot the exact amount posted
        emit Disputed(marketId, msg.sender, disputeBond);
    }

    /// @notice Admin (arbiter of last resort) resolves a dispute with the
    ///         authoritative winning outcome and settles the challenger's bond.
    /// @param upheld true if the challenge was correct (bond refunded), false if
    ///        rejected (bond forfeited to the treasury).
    function arbitrate(bytes32 marketId, uint8 finalOutcome, bool upheld) external onlyAdmin {
        address challenger = challengerOf[marketId];
        require(challenger != address(0), "CAT: no dispute");

        challengerOf[marketId] = address(0);
        uint256 bond = bondOf[marketId];
        bondOf[marketId] = 0;
        proposedOutcome[marketId] = finalOutcome; // admin's ruling is authoritative

        if (upheld) {
            require(collateral.transfer(challenger, bond), "CAT: refund bond");
        } else {
            collateral.approve(address(treasury), bond);
            treasury.collectFee(address(collateral), bond);
        }
        emit DisputeResolved(marketId, challenger, upheld);
        _finalize(marketId);
    }

    /// @dev Apply the (finalized) proposed outcome: an out-of-range/invalid index
    ///      or a winning pool with no stake voids the market (every principal
    ///      refundable); otherwise mark Resolved and skim the snapshotted fee from
    ///      the losing pool.
    function _finalize(bytes32 marketId) internal {
        Market storage m = _markets[marketId];
        uint8 outcome = proposedOutcome[marketId];

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
