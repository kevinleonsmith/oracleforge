// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {ForgeToken} from "../src/ForgeToken.sol";

/// @notice Focused review coverage for ForgeToken ($FORGE): the hard supply cap
///         on every mint path, minter gating + rotation, and the ERC-20
///         zero-address guards. Previously untested (only deployed in the script).
contract ForgeTokenTest is MiniTest {
    ForgeToken token;

    address minter = address(0x1111);
    address treasury = address(0x7EEA);
    address alice = address(0xA11CE);
    address bob = address(0xB0B);

    uint256 constant CAP = 100_000_000e18;
    uint256 constant GENESIS = 30_000_000e18;

    function setUp() public {
        token = new ForgeToken(minter, treasury, GENESIS);
    }

    function test_genesis_mintsToTreasury() public {
        assertEq(token.totalSupply(), GENESIS, "genesis supply");
        assertEq(token.balanceOf(treasury), GENESIS, "treasury funded");
        assertEq(token.minter(), minter, "minter set");
    }

    function test_mint_onlyMinter() public {
        vm.prank(alice);
        vm.expectRevert(bytes("FORGE: not minter"));
        token.mint(alice, 1e18);
    }

    function test_mint_byMinter_increasesSupply() public {
        vm.prank(minter);
        token.mint(alice, 1_000e18);
        assertEq(token.balanceOf(alice), 1_000e18, "alice minted");
        assertEq(token.totalSupply(), GENESIS + 1_000e18, "supply grew");
    }

    function test_mint_respectsCap_atBoundary() public {
        uint256 room = CAP - GENESIS;
        vm.prank(minter);
        token.mint(alice, room); // exactly fills the cap
        assertEq(token.totalSupply(), CAP, "cap reached");

        vm.prank(minter);
        vm.expectRevert(bytes("FORGE: cap"));
        token.mint(bob, 1); // one wei over
    }

    function test_constructorGenesis_cannotExceedCap() public {
        vm.expectRevert(bytes("FORGE: cap"));
        new ForgeToken(minter, treasury, CAP + 1);
    }

    function test_zeroGenesis_mintsNothing() public {
        ForgeToken t = new ForgeToken(minter, treasury, 0);
        assertEq(t.totalSupply(), 0, "no genesis");
    }

    function test_setMinter_rotatesAuthority() public {
        vm.prank(minter);
        token.setMinter(alice);
        assertEq(token.minter(), alice, "rotated");

        // old minter is now powerless; new one can mint
        vm.prank(minter);
        vm.expectRevert(bytes("FORGE: not minter"));
        token.mint(bob, 1e18);

        vm.prank(alice);
        token.mint(bob, 5e18);
        assertEq(token.balanceOf(bob), 5e18, "new minter works");
    }

    function test_setMinter_onlyMinter() public {
        vm.prank(alice);
        vm.expectRevert(bytes("FORGE: not minter"));
        token.setMinter(alice);
    }

    function test_setMinter_toZero_renouncesEmissions() public {
        // Setting the minter to the zero address permanently disables mint()
        // (no one can satisfy onlyMinter) — the intended way to cap emissions.
        vm.prank(minter);
        token.setMinter(address(0));
        assertEq(token.minter(), address(0), "renounced");
        vm.prank(minter);
        vm.expectRevert(bytes("FORGE: not minter"));
        token.mint(alice, 1e18);
    }

    function test_transfer_guardsZeroRecipient() public {
        vm.prank(minter);
        token.mint(alice, 10e18);
        vm.prank(alice);
        vm.expectRevert(bytes("ERC20: to zero"));
        token.transfer(address(0), 1e18);
    }
}
