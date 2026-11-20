// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {MarketEngine} from "../src/MarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {ChainlinkOracleAdapter} from "../src/oracle/ChainlinkOracleAdapter.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";

/// @notice Admin lifecycle: two-step rotation (review finding F5) and constructor
///         zero-address guards (F6). Isolated from market mechanics on purpose —
///         these are the privileged-role safety nets the economic tests don't touch.
contract MarketEngineAdminTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    ChainlinkOracleAdapter oracle;
    MarketEngine engine;

    address admin = address(0xA11CE);
    address newAdmin = address(0xBEEF);
    address stranger = address(0xBAD);

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 6);
        treasury = new Treasury(admin);
        oracle = new ChainlinkOracleAdapter();
        engine = new MarketEngine(address(collateral), address(oracle), address(treasury), admin);
        oracle.initEngine(address(engine));
    }

    // ------------------------------------------------------------- F5: rotation

    function test_transferAdmin_isTwoStep() public {
        vm.prank(admin);
        engine.transferAdmin(newAdmin);
        // nomination recorded, but the role has NOT moved yet
        assertEq(engine.admin(), admin, "admin unchanged until accepted");
        assertEq(engine.pendingAdmin(), newAdmin, "nominee pending");

        vm.prank(newAdmin);
        engine.acceptAdmin();
        assertEq(engine.admin(), newAdmin, "admin rotated");
        assertEq(engine.pendingAdmin(), address(0), "pending cleared");
    }

    function test_onlyAdmin_canNominate() public {
        vm.prank(stranger);
        vm.expectRevert(bytes("ENGINE: not admin"));
        engine.transferAdmin(stranger);
    }

    function test_onlyNominee_canAccept() public {
        vm.prank(admin);
        engine.transferAdmin(newAdmin);

        // a non-nominee (even the current admin) cannot complete the handover
        vm.prank(stranger);
        vm.expectRevert(bytes("ENGINE: not pending admin"));
        engine.acceptAdmin();

        vm.prank(admin);
        vm.expectRevert(bytes("ENGINE: not pending admin"));
        engine.acceptAdmin();
    }

    function test_nomination_canBeCancelled() public {
        vm.prank(admin);
        engine.transferAdmin(newAdmin);
        // superseding with address(0) cancels; the old nominee can no longer accept
        vm.prank(admin);
        engine.transferAdmin(address(0));
        assertEq(engine.pendingAdmin(), address(0), "nomination cleared");

        vm.prank(newAdmin);
        vm.expectRevert(bytes("ENGINE: not pending admin"));
        engine.acceptAdmin();
    }

    function test_rotatedAdmin_hasFullPowers_oldAdminLocked() public {
        vm.prank(admin);
        engine.transferAdmin(newAdmin);
        vm.prank(newAdmin);
        engine.acceptAdmin();

        // the new admin wields every onlyAdmin power
        vm.prank(newAdmin);
        engine.setFeeBps(100);
        assertEq(uint256(engine.feeBps()), 100, "new admin set fee");
        vm.prank(newAdmin);
        engine.setRelayer(stranger, true);
        assertTrue(engine.isRelayer(stranger), "new admin set relayer");

        // the old admin is fully demoted
        vm.prank(admin);
        vm.expectRevert(bytes("ENGINE: not admin"));
        engine.setFeeBps(0);
    }

    function test_rotation_canChainToAThirdAdmin() public {
        vm.prank(admin);
        engine.transferAdmin(newAdmin);
        vm.prank(newAdmin);
        engine.acceptAdmin();

        // the freshly-rotated admin can itself hand off again
        vm.prank(newAdmin);
        engine.transferAdmin(stranger);
        vm.prank(stranger);
        engine.acceptAdmin();
        assertEq(engine.admin(), stranger, "chained rotation");
    }

    // --------------------------------------------------- F6: zero-address guards

    function test_constructor_rejectsZeroCollateral() public {
        vm.expectRevert(bytes("ENGINE: collateral zero"));
        new MarketEngine(address(0), address(oracle), address(treasury), admin);
    }

    function test_constructor_rejectsZeroOracle() public {
        vm.expectRevert(bytes("ENGINE: oracle zero"));
        new MarketEngine(address(collateral), address(0), address(treasury), admin);
    }

    function test_constructor_rejectsZeroTreasury() public {
        vm.expectRevert(bytes("ENGINE: treasury zero"));
        new MarketEngine(address(collateral), address(oracle), address(0), admin);
    }

    function test_constructor_rejectsZeroAdmin() public {
        vm.expectRevert(bytes("ENGINE: admin zero"));
        new MarketEngine(address(collateral), address(oracle), address(treasury), address(0));
    }
}
