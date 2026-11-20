// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IMarketEngine} from "./interfaces/IMarketEngine.sol";
import {IOracleAdapter} from "./interfaces/IOracleAdapter.sol";
import {ITreasury} from "./interfaces/ITreasury.sol";
import {IERC20} from "./interfaces/IERC20.sol";

/// @title MarketEngine
/// @notice Parimutuel binary prediction market. Collateral is a single ERC-20.
///         Winners split the losing pool pro-rata to their stake, minus a
///         protocol fee skimmed at resolution and routed to the Treasury.
/// @dev MVP scaffold: parimutuel (not an LMSR/AMM) for clarity. Not audited.
contract MarketEngine is IMarketEngine {
    /// @notice Collateral token all markets are denominated in.
    IERC20 public immutable collateral;
    IOracleAdapter public immutable oracle;
    ITreasury public immutable treasury;

    /// @notice Default protocol fee (basis points) applied to markets at creation.
    ///         Each market snapshots this value; changing it affects only markets
    ///         opened afterward, never ones already accepting positions.
    uint16 public feeBps = 200; // 2.0%

    /// @notice Addresses allowed to create markets (the AI generator's relayer).
    mapping(address => bool) public isRelayer;
    address public admin;

    mapping(bytes32 => Market) internal _markets;
    // marketId => account => side => staked amount
    mapping(bytes32 => mapping(address => mapping(Side => uint256))) public stakeOf;
    mapping(bytes32 => mapping(address => bool)) public claimed;

    // --- optimistic resolution + dispute window ---
    /// @notice Seconds a proposed outcome can be challenged before it finalizes.
    ///         0 (the default) means resolve() finalizes immediately — the
    ///         original behavior — so the window is strictly opt-in.
    uint64 public challengeWindow;
    /// @notice Collateral a challenger must bond to dispute. 0 disables disputes.
    uint256 public disputeBond;

    mapping(bytes32 => IOracleAdapter.Outcome) public proposedOutcome; // set at resolve()
    mapping(bytes32 => uint64) public proposedAt; // timestamp the outcome was proposed
    mapping(bytes32 => address) public challengerOf; // nonzero while under dispute

    event RelayerUpdated(address indexed relayer, bool allowed);
    event FeeUpdated(uint16 feeBps);
    event ChallengeWindowUpdated(uint64 window);
    event DisputeBondUpdated(uint256 bond);
    event ResolutionProposed(bytes32 indexed marketId, uint8 proposed, uint64 at);
    event Disputed(bytes32 indexed marketId, address indexed challenger, uint256 bond);
    event DisputeResolved(bytes32 indexed marketId, address indexed challenger, bool upheld);

    modifier onlyAdmin() {
        require(msg.sender == admin, "ENGINE: not admin");
        _;
    }

    modifier onlyRelayer() {
        require(isRelayer[msg.sender], "ENGINE: not relayer");
        _;
    }

    constructor(address _collateral, address _oracle, address _treasury, address _admin) {
        collateral = IERC20(_collateral);
        oracle = IOracleAdapter(_oracle);
        treasury = ITreasury(_treasury);
        admin = _admin;
        isRelayer[_admin] = true;
    }

    // --------------------------------------------------------------------- admin

    function setRelayer(address relayer, bool allowed) external onlyAdmin {
        isRelayer[relayer] = allowed;
        emit RelayerUpdated(relayer, allowed);
    }

    function setFeeBps(uint16 _feeBps) external onlyAdmin {
        require(_feeBps <= 1000, "ENGINE: fee too high"); // max 10%
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

    /// @inheritdoc IMarketEngine
    function createMarket(
        bytes32 questionHash,
        uint64 closeAt,
        uint16 aiProbBps,
        bytes calldata oracleParams
    ) external onlyRelayer returns (bytes32 marketId) {
        require(closeAt > block.timestamp, "ENGINE: closeAt past");
        require(aiProbBps <= 10_000, "ENGINE: prob range");

        marketId = keccak256(abi.encodePacked(questionHash, closeAt, block.chainid));
        require(_markets[marketId].createdAt == 0, "ENGINE: exists");

        _markets[marketId] = Market({
            questionHash: questionHash,
            createdAt: uint64(block.timestamp),
            closeAt: closeAt,
            aiProbBps: aiProbBps,
            feeBps: feeBps, // snapshot the current protocol fee for this market
            status: Status.Open,
            outcome: 0,
            yesPool: 0,
            noPool: 0
        });

        oracle.configure(marketId, oracleParams);
        emit MarketCreated(marketId, questionHash, closeAt, aiProbBps);
    }

    /// @inheritdoc IMarketEngine
    function takePosition(bytes32 marketId, Side side, uint256 amount) external {
        Market storage m = _markets[marketId];
        require(m.createdAt != 0, "ENGINE: no market");
        require(m.status == Status.Open, "ENGINE: not open");
        require(block.timestamp < m.closeAt, "ENGINE: closed");
        require(amount > 0, "ENGINE: zero");

        require(collateral.transferFrom(msg.sender, address(this), amount), "ENGINE: pull");

        if (side == Side.Yes) m.yesPool += amount;
        else m.noPool += amount;
        stakeOf[marketId][msg.sender][side] += amount;

        emit PositionTaken(marketId, msg.sender, side, amount);
    }

    /// @inheritdoc IMarketEngine
    /// @dev Permissionless: anyone can poke resolution once the oracle is ready.
    ///      In production this is driven by Chainlink Automation.
    function resolve(bytes32 marketId) external {
        Market storage m = _markets[marketId];
        require(m.createdAt != 0, "ENGINE: no market");
        require(m.status == Status.Open, "ENGINE: not open");
        require(block.timestamp >= m.closeAt, "ENGINE: not closed");

        IOracleAdapter.Outcome o = oracle.resolve(marketId);
        require(o != IOracleAdapter.Outcome.Pending, "ENGINE: oracle pending");

        // Record the proposed outcome and open the challenge window.
        proposedOutcome[marketId] = o;
        proposedAt[marketId] = uint64(block.timestamp);
        m.status = Status.Closed; // "proposed, awaiting finalization"
        emit ResolutionProposed(marketId, uint8(o), uint64(block.timestamp));

        // Fast path: with no challenge window, finalize in the same call so the
        // market settles atomically (Open -> Resolved/Invalid), as before.
        if (challengeWindow == 0) _finalize(marketId);
    }

    /// @notice Lock in a proposed outcome once its challenge window has elapsed
    ///         and no dispute is open. Permissionless, like resolve().
    function finalize(bytes32 marketId) external {
        require(_markets[marketId].status == Status.Closed, "ENGINE: not proposed");
        require(challengerOf[marketId] == address(0), "ENGINE: disputed");
        require(
            block.timestamp >= proposedAt[marketId] + challengeWindow, "ENGINE: window open"
        );
        _finalize(marketId);
    }

    /// @notice Challenge a proposed outcome within its window by posting a bond.
    ///         Freezes finalization until the admin arbitrates. A rejected
    ///         challenge forfeits the bond to the treasury; an upheld one refunds it.
    function dispute(bytes32 marketId) external {
        require(_markets[marketId].status == Status.Closed, "ENGINE: not proposed");
        require(challengerOf[marketId] == address(0), "ENGINE: already disputed");
        require(disputeBond > 0, "ENGINE: disputes off");
        require(
            block.timestamp < proposedAt[marketId] + challengeWindow, "ENGINE: window closed"
        );
        require(
            collateral.transferFrom(msg.sender, address(this), disputeBond), "ENGINE: bond"
        );
        challengerOf[marketId] = msg.sender;
        emit Disputed(marketId, msg.sender, disputeBond);
    }

    /// @notice Admin (arbiter of last resort) resolves a dispute, setting the
    ///         authoritative outcome and settling the challenger's bond.
    /// @param upheld true if the challenge was correct (bond refunded), false if
    ///        rejected (bond forfeited to the treasury).
    function arbitrate(bytes32 marketId, IOracleAdapter.Outcome finalOutcome, bool upheld)
        external
        onlyAdmin
    {
        address challenger = challengerOf[marketId];
        require(challenger != address(0), "ENGINE: no dispute");
        require(finalOutcome != IOracleAdapter.Outcome.Pending, "ENGINE: pending");

        challengerOf[marketId] = address(0);
        proposedOutcome[marketId] = finalOutcome; // admin's ruling is authoritative

        if (upheld) {
            require(collateral.transfer(challenger, disputeBond), "ENGINE: refund bond");
        } else {
            collateral.approve(address(treasury), disputeBond);
            treasury.collectFee(address(collateral), disputeBond);
        }
        emit DisputeResolved(marketId, challenger, upheld);
        _finalize(marketId);
    }

    /// @dev Apply a (finalized) outcome: void on Invalid or a no-winner push,
    ///      otherwise mark Resolved and skim the market's snapshotted fee.
    function _finalize(bytes32 marketId) internal {
        Market storage m = _markets[marketId];
        IOracleAdapter.Outcome o = proposedOutcome[marketId];

        if (o == IOracleAdapter.Outcome.Invalid) {
            m.status = Status.Invalid;
            emit MarketResolved(marketId, type(uint8).max, 0);
            return;
        }

        bool yesWon = (o == IOracleAdapter.Outcome.Yes);
        uint256 winningPool = yesWon ? m.yesPool : m.noPool;

        // No stake on the winning side — the market is a push. Void it so every
        // participant is refunded their principal. Otherwise claim() (which needs
        // winningPool > 0 as the pro-rata denominator) can never pay anyone and
        // the losing pool would be stranded in the contract forever.
        if (winningPool == 0) {
            m.status = Status.Invalid;
            emit MarketResolved(marketId, type(uint8).max, 0);
            return;
        }

        m.outcome = yesWon ? 1 : 0;
        m.status = Status.Resolved;

        // Fee is skimmed from the losing pool (winners' principal is untouched),
        // at the rate snapshotted when the market opened — not the current global
        // feeBps, so an admin can't change the terms of an in-flight market.
        uint256 losingPool = yesWon ? m.noPool : m.yesPool;
        uint256 fee = (losingPool * m.feeBps) / 10_000;
        if (fee > 0) {
            collateral.approve(address(treasury), fee);
            treasury.collectFee(address(collateral), fee);
            // reduce the distributable losing pool by the fee
            if (yesWon) m.noPool -= fee;
            else m.yesPool -= fee;
        }
        emit MarketResolved(marketId, m.outcome, fee);
    }

    /// @inheritdoc IMarketEngine
    function claim(bytes32 marketId) external returns (uint256 payout) {
        Market storage m = _markets[marketId];
        require(!claimed[marketId][msg.sender], "ENGINE: claimed");

        if (m.status == Status.Invalid) {
            // Refund both sides at principal.
            uint256 refund = stakeOf[marketId][msg.sender][Side.Yes]
                + stakeOf[marketId][msg.sender][Side.No];
            require(refund > 0, "ENGINE: nothing");
            claimed[marketId][msg.sender] = true;
            require(collateral.transfer(msg.sender, refund), "ENGINE: refund");
            emit Claimed(marketId, msg.sender, refund);
            return refund;
        }

        require(m.status == Status.Resolved, "ENGINE: unresolved");
        Side winning = m.outcome == 1 ? Side.Yes : Side.No;
        uint256 stake = stakeOf[marketId][msg.sender][winning];
        require(stake > 0, "ENGINE: no winnings");

        uint256 winningPool = m.outcome == 1 ? m.yesPool : m.noPool;
        uint256 losingPool = m.outcome == 1 ? m.noPool : m.yesPool;

        // principal + pro-rata share of the (fee-reduced) losing pool
        payout = stake + (stake * losingPool) / winningPool;

        claimed[marketId][msg.sender] = true;
        require(collateral.transfer(msg.sender, payout), "ENGINE: payout");
        emit Claimed(marketId, msg.sender, payout);
    }

    /// @inheritdoc IMarketEngine
    function getMarket(bytes32 marketId) external view returns (Market memory) {
        return _markets[marketId];
    }
}
