// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {CategoricalMarketEngine} from "../src/CategoricalMarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockCategoricalOracle} from "../src/mocks/MockCategoricalOracle.sol";

/// @notice Optimistic dispute-window coverage for the categorical engine: a
///         proposed winning outcome must survive the window (or an admin
///         arbitration) before it settles; disputes bond, freeze finalization,
///         and are arbitrated with the bond refunded (upheld) or forfeited
///         (rejected). The admin can override the winner — or void by ruling an
///         out-of-range index.
contract CategoricalMarketEngineDisputeTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    MockCategoricalOracle oracle;
    CategoricalMarketEngine engine;

    address admin = address(0xA11CE);
    address alice = address(0xA1); // outcome 0
    address bob = address(0xB0); // outcome 1
    address carol = address(0xCA); // challenger

    uint64 constant WINDOW = 1 days;
    uint256 constant BOND = 100e18;
    bytes32 id;

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(admin);
        oracle = new MockCategoricalOracle();
        engine = new CategoricalMarketEngine(address(collateral), address(oracle), address(treasury), admin);

        vm.prank(admin);
        engine.setChallengeWindow(WINDOW);
        vm.prank(admin);
        engine.setDisputeBond(BOND);

        address[3] memory who = [alice, bob, carol];
        for (uint256 i; i < 3; i++) {
            collateral.mint(who[i], 10_000e18);
            vm.prank(who[i]);
            collateral.approve(address(engine), type(uint256).max);
        }

        // 3-outcome book: outcome 0 = Alice 600, outcome 1 = Bob 400, outcome 2 empty.
        vm.prank(admin);
        id = engine.createMarket(keccak256("who wins?"), uint64(block.timestamp + 7 days), 3, "");
        vm.prank(alice);
        engine.takePosition(id, 0, 600);
        vm.prank(bob);
        engine.takePosition(id, 1, 400);
    }

    function _propose(uint8 outcome) internal {
        vm.warp(block.timestamp + 8 days);
        oracle.set(id, outcome);
        engine.resolve(id); // proposes, does NOT finalize (window > 0)
    }

    function _claim(address who) internal returns (uint256) {
        vm.prank(who);
        return engine.claim(id);
    }

    // --------------------------------------------------------------- happy path

    function test_resolveProposesButDoesNotSettle() public {
        _propose(0);
        CategoricalMarketEngine.Market memory m = engine.getMarket(id);
        assertEq(uint256(uint8(m.status)), 1, "Closed (proposed)");
        assertEq(uint256(engine.proposedOutcome(id)), 0, "proposed outcome 0");
        // claim is not open yet
        vm.prank(alice);
        vm.expectRevert(bytes("CAT: unresolved"));
        engine.claim(id);
    }

    function test_finalizeAfterWindowSettles() public {
        _propose(0);
        vm.warp(block.timestamp + WINDOW + 1);
        engine.finalize(id);
        CategoricalMarketEngine.Market memory m = engine.getMarket(id);
        assertEq(uint256(uint8(m.status)), 2, "Resolved");
        // outcome 0 wins: losing 400, fee 8, net 392 -> Alice 600 + 392 = 992
        assertEq(collateral.balanceOf(address(treasury)), 8, "fee");
        assertEq(_claim(alice), 992, "alice payout");
    }

    function test_finalizeRevertsWhileWindowOpen() public {
        _propose(0);
        vm.expectRevert(bytes("CAT: window open"));
        engine.finalize(id);
    }

    // --------------------------------------------------------------- disputes

    function test_disputeFreezesFinalize() public {
        _propose(0);
        vm.prank(carol);
        engine.dispute(id);
        assertEq(engine.challengerOf(id), carol, "challenger set");
        vm.warp(block.timestamp + WINDOW + 1);
        vm.expectRevert(bytes("CAT: disputed"));
        engine.finalize(id);
    }

    function test_disputeRequiresOpenWindow() public {
        _propose(0);
        vm.warp(block.timestamp + WINDOW + 1); // window closed
        vm.prank(carol);
        vm.expectRevert(bytes("CAT: window closed"));
        engine.dispute(id);
    }

    function test_arbitrateUpheldRefundsBondAndOverridesWinner() public {
        _propose(0); // oracle said outcome 0
        uint256 before = collateral.balanceOf(carol);
        vm.prank(carol);
        engine.dispute(id);
        // admin rules the true winner is outcome 1, challenge upheld -> refund bond
        vm.prank(admin);
        engine.arbitrate(id, 1, true);

        CategoricalMarketEngine.Market memory m = engine.getMarket(id);
        assertEq(uint256(uint8(m.status)), 2, "Resolved");
        assertEq(uint256(m.winningOutcome), 1, "winner overridden to 1");
        assertEq(collateral.balanceOf(carol), before, "bond refunded in full");
        // outcome 1 wins: losing 600, fee 12, net 588 -> Bob 400 + 588 = 988
        assertEq(_claim(bob), 988, "bob (new winner) paid");
        assertEq(engine.bondOf(id), 0, "bond cleared");
    }

    function test_arbitrateRejectedForfeitsBondToTreasury() public {
        _propose(0);
        vm.prank(carol);
        engine.dispute(id);
        // challenge rejected: outcome 0 stands, bond forfeited to treasury
        vm.prank(admin);
        engine.arbitrate(id, 0, false);

        // outcome 0 wins: losing 400, fee 8; treasury gets fee + forfeited bond
        assertEq(collateral.balanceOf(address(treasury)), 8 + BOND, "fee + bond forfeited");
        assertEq(_claim(alice), 992, "alice (original winner) paid");
    }

    function test_arbitrateCanVoidByRulingOutOfRange() public {
        _propose(0);
        uint256 before = collateral.balanceOf(carol);
        vm.prank(carol);
        engine.dispute(id);
        // admin voids by ruling an out-of-range index (invalid), challenge upheld
        vm.prank(admin);
        engine.arbitrate(id, type(uint8).max, true);

        CategoricalMarketEngine.Market memory m = engine.getMarket(id);
        assertEq(uint256(uint8(m.status)), 3, "Invalid (voided)");
        assertEq(collateral.balanceOf(carol), before, "bond refunded");
        assertEq(_claim(alice), 600, "alice refunded principal");
        assertEq(_claim(bob), 400, "bob refunded principal");
    }

    function test_onlyAdminArbitrates() public {
        _propose(0);
        vm.prank(carol);
        engine.dispute(id);
        vm.prank(carol);
        vm.expectRevert(bytes("CAT: not admin"));
        engine.arbitrate(id, 1, true);
    }

    function test_zeroWindowStillSettlesAtomically() public {
        // turning the window off restores v1 behavior: resolve() finalizes in one call
        vm.prank(admin);
        engine.setChallengeWindow(0);
        _propose(0);
        CategoricalMarketEngine.Market memory m = engine.getMarket(id);
        assertEq(uint256(uint8(m.status)), 2, "Resolved atomically");
    }
}
