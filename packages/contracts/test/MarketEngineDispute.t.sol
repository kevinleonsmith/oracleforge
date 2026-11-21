// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {MarketEngine} from "../src/MarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockOracleAdapter} from "../src/mocks/MockOracleAdapter.sol";
import {IMarketEngine} from "../src/interfaces/IMarketEngine.sol";
import {IOracleAdapter} from "../src/interfaces/IOracleAdapter.sol";

/// @notice Exercises the optimistic-resolution + dispute window. With a nonzero
///         challengeWindow, resolve() only *proposes* an outcome; it must survive
///         the window (or an admin arbitration) before claims open. The
///         back-compatible zero-window path is covered by the rest of the suite,
///         which runs at the default window of 0.
contract MarketEngineDisputeTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    MockOracleAdapter oracle;
    MarketEngine engine;

    address admin = address(0xA11CE);
    address alice = address(0xA1); // YES
    address bob = address(0xB0); // NO
    address charlie = address(0xC0); // challenger
    bytes32 constant OPS = keccak256("OPERATIONS");

    uint64 constant WINDOW = 1 hours;
    uint256 constant BOND = 100e18;

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(admin);
        oracle = new MockOracleAdapter();
        engine = new MarketEngine(address(collateral), address(oracle), address(treasury), admin);
        vm.startPrank(admin);
        engine.setChallengeWindow(WINDOW);
        engine.setDisputeBond(BOND);
        vm.stopPrank();
    }

    // --- helpers ----------------------------------------------------------
    function _open() internal returns (bytes32 id) {
        vm.prank(admin);
        id = engine.createMarket(keccak256("q"), uint64(block.timestamp + 7 days), 5000, "");
    }

    function _take(address who, bytes32 id, IMarketEngine.Side side, uint256 amt) internal {
        collateral.mint(who, amt);
        vm.startPrank(who);
        collateral.approve(address(engine), amt);
        engine.takePosition(id, side, amt);
        vm.stopPrank();
    }

    /// Open, stake 1000 YES (alice) + 1000 NO (bob), warp past close, propose YES.
    function _proposeYes() internal returns (bytes32 id) {
        id = _open();
        _take(alice, id, IMarketEngine.Side.Yes, 1000e18);
        _take(bob, id, IMarketEngine.Side.No, 1000e18);
        oracle.setOutcome(id, IOracleAdapter.Outcome.Yes);
        vm.warp(block.timestamp + 8 days);
        engine.resolve(id); // proposes only (window > 0)
    }

    function _postBond(address who, bytes32 id) internal {
        collateral.mint(who, BOND);
        vm.startPrank(who);
        collateral.approve(address(engine), BOND);
        engine.dispute(id);
        vm.stopPrank();
    }

    function _status(bytes32 id) internal view returns (uint8) {
        return uint8(engine.getMarket(id).status);
    }

    // --- tests ------------------------------------------------------------

    /// resolve() only proposes while a window is set: claims are blocked and
    /// finalize() reverts until the window elapses, then payouts open.
    function test_window_blocksClaimUntilFinalized() public {
        bytes32 id = _proposeYes();
        assertEq(_status(id), uint8(IMarketEngine.Status.Closed), "proposed, not resolved");

        vm.prank(alice);
        vm.expectRevert(bytes("ENGINE: unresolved"));
        engine.claim(id);

        vm.expectRevert(bytes("ENGINE: window open"));
        engine.finalize(id);

        vm.warp(block.timestamp + WINDOW);
        engine.finalize(id);
        assertEq(_status(id), uint8(IMarketEngine.Status.Resolved), "resolved after window");

        vm.prank(alice);
        assertEq(engine.claim(id), 1980e18, "winner paid 1000 + 980");
        assertEq(treasury.reserves(OPS, address(collateral)), 20e18, "2% fee to treasury");
    }

    /// A dispute freezes finalization even past the window; a rejected challenge
    /// forfeits the bond to the treasury and the proposed outcome stands.
    function test_dispute_rejected_forfeitsBond_outcomeStands() public {
        bytes32 id = _proposeYes();
        _postBond(charlie, id);
        assertEq(engine.challengerOf(id), charlie, "charlie is the challenger");

        vm.warp(block.timestamp + WINDOW);
        vm.expectRevert(bytes("ENGINE: disputed"));
        engine.finalize(id);

        vm.prank(admin);
        engine.arbitrate(id, IOracleAdapter.Outcome.Yes, false); // reject

        assertEq(engine.challengerOf(id), address(0), "dispute cleared");
        assertEq(_status(id), uint8(IMarketEngine.Status.Resolved), "resolved YES");
        assertEq(
            treasury.reserves(OPS, address(collateral)), 20e18 + BOND, "fee + forfeited bond"
        );
        vm.prank(alice);
        assertEq(engine.claim(id), 1980e18, "YES winner still paid");
    }

    /// An upheld challenge refunds the bond and the admin's ruling becomes the
    /// authoritative outcome — flipping who wins.
    function test_dispute_upheld_refundsBond_appliesAdminOutcome() public {
        bytes32 id = _proposeYes();
        _postBond(charlie, id);

        uint256 charlieBefore = collateral.balanceOf(charlie);
        vm.prank(admin);
        engine.arbitrate(id, IOracleAdapter.Outcome.No, true); // uphold -> real outcome NO

        assertEq(collateral.balanceOf(charlie) - charlieBefore, BOND, "bond refunded");
        IMarketEngine.Market memory m = engine.getMarket(id);
        assertEq(uint8(m.status), uint8(IMarketEngine.Status.Resolved), "resolved");
        assertEq(uint256(m.outcome), 0, "outcome flipped to NO");

        vm.prank(bob);
        assertEq(engine.claim(id), 1980e18, "NO now wins");
        assertEq(treasury.reserves(OPS, address(collateral)), 20e18, "only the fee, bond refunded");

        vm.prank(alice);
        vm.expectRevert(bytes("ENGINE: no winnings"));
        engine.claim(id); // the YES side lost
    }

    /// The bond is snapshotted at dispute time: raising the global disputeBond
    /// after a challenge is open must not change what a rejected challenge forfeits.
    /// (Without the bondOf snapshot the engine would forfeit the mutated global,
    /// draining the pot to over-pay the treasury.)
    function test_dispute_rejected_forfeitsPostedBond_notMutatedGlobal() public {
        bytes32 id = _proposeYes();
        _postBond(charlie, id); // posts BOND (100e18)
        assertEq(engine.bondOf(id), BOND, "bond snapshotted");

        // Admin raises the global bond 5x while the dispute is open.
        vm.prank(admin);
        engine.setDisputeBond(5 * BOND);

        vm.prank(admin);
        engine.arbitrate(id, IOracleAdapter.Outcome.Yes, false); // reject

        assertEq(engine.bondOf(id), 0, "bond cleared");
        assertEq(
            treasury.reserves(OPS, address(collateral)),
            20e18 + BOND,
            "fee + the POSTED bond, not the mutated global"
        );
        // Winners are still paid in full from the untouched pot.
        vm.prank(alice);
        assertEq(engine.claim(id), 1980e18, "YES winner paid from the intact pot");
    }

    /// The mirror: lowering the global bond after a challenge is open must not
    /// short the refund of an upheld challenge — the challenger gets back exactly
    /// what they posted.
    function test_dispute_upheld_refundsPostedBond_notMutatedGlobal() public {
        bytes32 id = _proposeYes();
        _postBond(charlie, id); // posts BOND (100e18)

        // Admin slashes the global bond while the dispute is open.
        vm.prank(admin);
        engine.setDisputeBond(1e18);

        uint256 charlieBefore = collateral.balanceOf(charlie);
        vm.prank(admin);
        engine.arbitrate(id, IOracleAdapter.Outcome.No, true); // uphold

        assertEq(
            collateral.balanceOf(charlie) - charlieBefore, BOND, "refunded the POSTED bond, in full"
        );
        assertEq(treasury.reserves(OPS, address(collateral)), 20e18, "only the fee, bond refunded");
    }

    /// Disputes are only possible inside the window.
    function test_dispute_afterWindow_reverts() public {
        bytes32 id = _proposeYes();
        vm.warp(block.timestamp + WINDOW);
        collateral.mint(charlie, BOND);
        vm.startPrank(charlie);
        collateral.approve(address(engine), BOND);
        vm.expectRevert(bytes("ENGINE: window closed"));
        engine.dispute(id);
        vm.stopPrank();
    }

    /// With the bond set to zero, disputes are disabled entirely.
    function test_disputesDisabled_whenBondZero() public {
        bytes32 id = _proposeYes();
        vm.prank(admin);
        engine.setDisputeBond(0);

        collateral.mint(charlie, 1);
        vm.startPrank(charlie);
        collateral.approve(address(engine), 1);
        vm.expectRevert(bytes("ENGINE: disputes off"));
        engine.dispute(id);
        vm.stopPrank();
    }
}
