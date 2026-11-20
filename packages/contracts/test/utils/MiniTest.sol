// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Minimal Foundry cheatcode interface (subset) so the suite needs no
///         forge-std install and the repo builds offline.
interface Vm {
    function warp(uint256) external;
    function prank(address) external;
    function startPrank(address) external;
    function stopPrank() external;
    function expectRevert(bytes calldata) external;
    function label(address, string calldata) external;
}

/// @notice Tiny assertion base. A reverting test function is a failing test in
///         `forge test`, so assertions revert with a message on failure.
abstract contract MiniTest {
    Vm internal constant vm = Vm(0x7109709ECfa91a80626fF3989D68f67F5b1DD12D);

    function assertTrue(bool c, string memory m) internal pure {
        require(c, m);
    }

    function assertEq(uint256 a, uint256 b, string memory m) internal pure {
        require(a == b, m);
    }

    function assertGe(uint256 a, uint256 b, string memory m) internal pure {
        require(a >= b, m);
    }

    function assertLe(uint256 a, uint256 b, string memory m) internal pure {
        require(a <= b, m);
    }

    /// @notice Clamp a fuzzed value into [lo, hi] (no forge-std `bound`).
    function _bound(uint256 x, uint256 lo, uint256 hi) internal pure returns (uint256) {
        require(hi >= lo, "bound: hi<lo");
        return lo + (x % (hi - lo + 1));
    }
}
