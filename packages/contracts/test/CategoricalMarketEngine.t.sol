// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {CategoricalMarketEngine} from "../src/CategoricalMarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockCategoricalOracle} from "../src/mocks/MockCategoricalOracle.sol";

/// @notice Lifecycle + settlement coverage for the categorical (N-outcome) engine:
///         outcome-count validation, per-outcome positions, winner-take-all
///         pro-rata settlement across a concrete book, fee snapshotting, the
///         no-winner and invalid-sentinel voids, and the N=2 == binary case.
contract CategoricalMarketEngineTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    MockCategoricalOracle oracle;
    CategoricalMarketEngine engine;

    address admin = address(0xA11CE);
    address alice = address(0xA1);
    address bob = address(0xB0);
    address carol = address(0xCA);
    address dave = address(0xDA);

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(admin);
        oracle = new MockCategoricalOracle();
        engine = new CategoricalMarketEngine(address(collateral), address(oracle), address(treasury), admin);

        address[4] memory who = [alice, bob, carol, dave];
        for (uint256 i; i < 4; i++) {
            collateral.mint(who[i], 10_000e18);
            vm.prank(who[i]);
            collateral.approve(address(engine), type(uint256).max);
        }
    }

    function _create(uint8 n) internal returns (bytes32 id) {
        vm.prank(admin);
        id = engine.createMarket(keccak256("who wins?"), uint64(block.timestamp + 7 days), n, "");
    }

    function _take(bytes32 id, address who, uint8 outcome, uint256 amt) internal {
        vm.prank(who);
        engine.takePosition(id, outcome, amt);
    }

    function _resolve(bytes32 id, uint8 outcome) internal {
        vm.warp(block.timestamp + 8 days);
        oracle.set(id, outcome);
        engine.resolve(id);
    }

    function _claim(bytes32 id, address who) internal returns (uint256) {
        vm.prank(who);
        return engine.claim(id);
    }

    // --------------------------------------------------------------- creation

    function test_create_storesOutcomeCount() public {
        bytes32 id = _create(3);
        CategoricalMarketEngine.Market memory m = engine.getMarket(id);
        assertEq(uint256(m.outcomeCount), 3, "N stored");
        assertEq(m.pools.length, 3, "pools length N");
        assertEq(uint256(m.feeBps), 200, "fee snapshot");
        assertEq(uint256(uint8(m.status)), 0, "open");
    }

    function test_create_rejectsTooFewOutcomes() public {
        vm.prank(admin);
        vm.expectRevert(bytes("CAT: outcomes"));
        engine.createMarket(keccak256("x"), uint64(block.timestamp + 1 days), 1, "");
    }

    function test_create_rejectsTooManyOutcomes() public {
        vm.prank(admin);
        vm.expectRevert(bytes("CAT: outcomes"));
        engine.createMarket(keccak256("x"), uint64(block.timestamp + 1 days), 65, "");
    }

    function test_create_onlyRelayer() public {
        vm.prank(alice);
        vm.expectRevert(bytes("CAT: not relayer"));
        engine.createMarket(keccak256("x"), uint64(block.timestamp + 1 days), 3, "");
    }

    function test_create_rejectsPastClose() public {
        vm.prank(admin);
        vm.expectRevert(bytes("CAT: closeAt past"));
        engine.createMarket(keccak256("x"), uint64(block.timestamp), 3, "");
    }

    function test_create_rejectsDuplicate() public {
        _create(3);
        vm.prank(admin);
        vm.expectRevert(bytes("CAT: exists"));
        engine.createMarket(keccak256("who wins?"), uint64(block.timestamp + 7 days), 3, "");
    }

    function test_constructor_rejectsZeroAddresses() public {
        vm.expectRevert(bytes("CAT: collateral zero"));
        new CategoricalMarketEngine(address(0), address(oracle), address(treasury), admin);
        vm.expectRevert(bytes("CAT: oracle zero"));
        new CategoricalMarketEngine(address(collateral), address(0), address(treasury), admin);
        vm.expectRevert(bytes("CAT: treasury zero"));
        new CategoricalMarketEngine(address(collateral), address(oracle), address(0), admin);
        vm.expectRevert(bytes("CAT: admin zero"));
        new CategoricalMarketEngine(address(collateral), address(oracle), address(treasury), address(0));
    }

    // --------------------------------------------------------------- positions

    function test_takePosition_accumulatesPools() public {
        bytes32 id = _create(3);
        _take(id, alice, 0, 600);
        _take(id, bob, 0, 400);
        _take(id, carol, 2, 500);
        assertEq(engine.poolOf(id, 0), 1000, "pool 0");
        assertEq(engine.poolOf(id, 1), 0, "pool 1 empty");
        assertEq(engine.poolOf(id, 2), 500, "pool 2");
        assertEq(engine.stakeOf(id, alice, 0), 600, "alice stake");
    }

    function test_takePosition_rejectsOutOfRangeOutcome() public {
        bytes32 id = _create(3);
        vm.prank(alice);
        vm.expectRevert(bytes("CAT: outcome range"));
        engine.takePosition(id, 3, 100); // valid outcomes are 0,1,2
    }

    function test_takePosition_rejectsZero() public {
        bytes32 id = _create(3);
        vm.prank(alice);
        vm.expectRevert(bytes("CAT: zero"));
        engine.takePosition(id, 0, 0);
    }

    function test_takePosition_rejectsAfterClose() public {
        bytes32 id = _create(3);
        vm.warp(block.timestamp + 8 days);
        vm.prank(alice);
        vm.expectRevert(bytes("CAT: closed"));
        engine.takePosition(id, 0, 100);
    }

    // --------------------------------------------------------------- settlement

    /// Book: outcome 0 = Alice 600 + Bob 400 (1000); outcome 1 = Carol 500;
    /// outcome 2 = Dave 500. Winner = 0. pot 2000, losing 1000, fee 2% = 20,
    /// distributable 980. Alice 600+588=1188, Bob 400+392=792; Carol/Dave lose.
    function test_resolve_paysWinnersProRata() public {
        bytes32 id = _create(3);
        _take(id, alice, 0, 600);
        _take(id, bob, 0, 400);
        _take(id, carol, 1, 500);
        _take(id, dave, 2, 500);

        _resolve(id, 0);

        CategoricalMarketEngine.Market memory m = engine.getMarket(id);
        assertEq(uint256(uint8(m.status)), 1, "resolved");
        assertEq(uint256(m.winningOutcome), 0, "winner 0");
        assertEq(collateral.balanceOf(address(treasury)), 20, "fee 2% of losing pool");

        assertEq(_claim(id, alice), 1188, "alice payout");
        assertEq(_claim(id, bob), 792, "bob payout");
    }

    function test_resolve_loserCannotClaim() public {
        bytes32 id = _create(3);
        _take(id, alice, 0, 600);
        _take(id, carol, 1, 500);
        _resolve(id, 0);
        vm.prank(carol);
        vm.expectRevert(bytes("CAT: no winnings"));
        engine.claim(id);
    }

    function test_claim_doubleClaimReverts() public {
        bytes32 id = _create(3);
        _take(id, alice, 0, 600);
        _take(id, carol, 1, 500);
        _resolve(id, 0);
        _claim(id, alice);
        vm.prank(alice);
        vm.expectRevert(bytes("CAT: claimed"));
        engine.claim(id);
    }

    /// Fee is snapshotted at creation, so changing the global fee afterward does
    /// not alter an in-flight market's economics.
    function test_resolve_usesSnapshottedFee() public {
        bytes32 id = _create(3);
        _take(id, alice, 0, 1000);
        _take(id, carol, 1, 1000);
        vm.prank(admin);
        engine.setFeeBps(1000); // 10% going forward — must not affect this market
        _resolve(id, 0);
        // fee is still 2% of the 1000 losing pool = 20
        assertEq(collateral.balanceOf(address(treasury)), 20, "snapshot fee used");
    }

    // --------------------------------------------------------------- voids

    /// Nobody staked the winning outcome -> void & refund every principal.
    function test_resolve_voidsWhenWinningPoolEmpty() public {
        bytes32 id = _create(3);
        _take(id, alice, 0, 600);
        _take(id, carol, 1, 500);
        _resolve(id, 2); // outcome 2 has no stake

        CategoricalMarketEngine.Market memory m = engine.getMarket(id);
        assertEq(uint256(uint8(m.status)), 2, "invalid");
        assertEq(collateral.balanceOf(address(treasury)), 0, "no fee on void");
        assertEq(_claim(id, alice), 600, "alice refunded principal");
        assertEq(_claim(id, carol), 500, "carol refunded principal");
    }

    /// The oracle's invalid sentinel (out of range) voids the market.
    function test_resolve_voidsOnInvalidSentinel() public {
        bytes32 id = _create(3);
        _take(id, alice, 0, 600);
        _take(id, carol, 1, 500);
        vm.warp(block.timestamp + 8 days);
        oracle.setInvalid(id);
        engine.resolve(id);

        CategoricalMarketEngine.Market memory m = engine.getMarket(id);
        assertEq(uint256(uint8(m.status)), 2, "invalid");
        assertEq(_claim(id, alice), 600, "alice refunded");
    }

    function test_resolve_rejectsBeforeClose() public {
        bytes32 id = _create(3);
        _take(id, alice, 0, 600);
        _take(id, carol, 1, 500);
        oracle.set(id, 0);
        vm.expectRevert(bytes("CAT: not closed"));
        engine.resolve(id);
    }

    function test_resolve_rejectsOraclePending() public {
        bytes32 id = _create(3);
        _take(id, alice, 0, 600);
        _take(id, carol, 1, 500);
        vm.warp(block.timestamp + 8 days);
        vm.expectRevert(bytes("CAT: oracle pending"));
        engine.resolve(id); // oracle never set -> not ready
    }

    // --------------------------------------------------------------- generality

    /// The N=2 case is exactly the binary engine: the single winning outcome
    /// takes the whole losing pool (net of fee) on top of principal.
    function test_binaryIsTheTwoOutcomeCase() public {
        bytes32 id = _create(2);
        _take(id, alice, 1, 1000); // "Yes"
        _take(id, bob, 0, 800); // "No"
        _resolve(id, 1); // Yes wins
        // losing 800, fee 16, distributable 784 -> Alice 1000 + 784 = 1784
        assertEq(collateral.balanceOf(address(treasury)), 16, "fee");
        assertEq(_claim(id, alice), 1784, "winner takes losing pool net");
    }

    // --------------------------------------------------------------- admin

    function test_admin_twoStepTransfer() public {
        vm.prank(admin);
        engine.transferAdmin(bob);
        assertEq(engine.pendingAdmin(), bob, "pending set");
        assertEq(engine.admin(), admin, "unchanged until accepted");
        vm.prank(bob);
        engine.acceptAdmin();
        assertEq(engine.admin(), bob, "bob is admin");
        assertEq(engine.pendingAdmin(), address(0), "pending cleared");
    }

    function test_admin_onlyNomineeAccepts() public {
        vm.prank(admin);
        engine.transferAdmin(bob);
        vm.prank(carol);
        vm.expectRevert(bytes("CAT: not pending admin"));
        engine.acceptAdmin();
    }
}
