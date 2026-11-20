// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {MarketEngine} from "../src/MarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockOracleAdapter} from "../src/mocks/MockOracleAdapter.sol";
import {IMarketEngine} from "../src/interfaces/IMarketEngine.sol";
import {IOracleAdapter} from "../src/interfaces/IOracleAdapter.sol";

/// @notice Property-based fuzz tests for parimutuel settlement. Where
///         `MarketEngine.t.sol` checks fixed scenarios and the anvil devnet
///         checks one scenario on a live node, these assert the settlement
///         *invariants* hold across the whole input space: value is conserved,
///         nobody is overpaid, the fee is exact, and the claim guards hold.
contract MarketEngineFuzzTest is MiniTest {
    MockERC20 collateral;
    Treasury treasury;
    MockOracleAdapter oracle;
    MarketEngine engine;

    address admin = address(0xA11CE);
    address[4] traders = [address(0xA1), address(0xA2), address(0xB1), address(0xB2)];
    // first two bet YES, last two bet NO
    bytes32 constant OPS = keccak256("OPERATIONS");

    uint256 constant MIN_STAKE = 1;
    uint256 constant MAX_STAKE = 1e24; // 1,000,000 tokens at 18 decimals

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 18);
        treasury = new Treasury(admin);
        oracle = new MockOracleAdapter();
        engine = new MarketEngine(address(collateral), address(oracle), address(treasury), admin);
    }

    // --- helpers ----------------------------------------------------------
    function _open() internal returns (bytes32 id) {
        vm.prank(admin);
        id = engine.createMarket(
            keccak256("fuzz market"), uint64(block.timestamp + 7 days), 5000, ""
        );
    }

    function _take(bytes32 id, address who, IMarketEngine.Side side, uint256 amount) internal {
        collateral.mint(who, amount);
        vm.startPrank(who);
        collateral.approve(address(engine), amount);
        engine.takePosition(id, side, amount);
        vm.stopPrank();
    }

    function _stakes(uint96 a, uint96 b, uint96 c, uint96 d)
        internal
        pure
        returns (uint256[4] memory s)
    {
        s[0] = _bound(a, MIN_STAKE, MAX_STAKE);
        s[1] = _bound(b, MIN_STAKE, MAX_STAKE);
        s[2] = _bound(c, MIN_STAKE, MAX_STAKE);
        s[3] = _bound(d, MIN_STAKE, MAX_STAKE);
    }

    function _setupResolved(uint96 a, uint96 b, uint96 c, uint96 d, bool yesWins)
        internal
        returns (bytes32 id, uint256[4] memory s)
    {
        s = _stakes(a, b, c, d);
        id = _open();
        _take(id, traders[0], IMarketEngine.Side.Yes, s[0]);
        _take(id, traders[1], IMarketEngine.Side.Yes, s[1]);
        _take(id, traders[2], IMarketEngine.Side.No, s[2]);
        _take(id, traders[3], IMarketEngine.Side.No, s[3]);

        oracle.setOutcome(id, yesWins ? IOracleAdapter.Outcome.Yes : IOracleAdapter.Outcome.No);
        vm.warp(block.timestamp + 8 days);
        engine.resolve(id);
    }

    function _claim(bytes32 id, address who) internal returns (uint256 payout) {
        vm.prank(who);
        payout = engine.claim(id);
    }

    // --- invariants -------------------------------------------------------

    /// Token conservation: every unit staked ends up as fee + payouts + the
    /// floor-division dust left in the engine. Nothing is created or destroyed.
    function testFuzz_valueIsConserved(uint96 a, uint96 b, uint96 c, uint96 d, bool yesWins)
        public
    {
        (bytes32 id, uint256[4] memory s) = _setupResolved(a, b, c, d, yesWins);
        uint256 totalStaked = s[0] + s[1] + s[2] + s[3];

        uint256 paid;
        if (yesWins) {
            paid += _claim(id, traders[0]);
            paid += _claim(id, traders[1]);
        } else {
            paid += _claim(id, traders[2]);
            paid += _claim(id, traders[3]);
        }
        uint256 fee = treasury.reserves(OPS, address(collateral));
        uint256 dust = collateral.balanceOf(address(engine));

        assertEq(paid + fee + dust, totalStaked, "value conserved");
    }

    /// The fee is exactly feeBps of the losing pool, and dust is sub-wei-ish
    /// (strictly less than the number of winners, i.e. <= 1 here per claim).
    function testFuzz_feeIsExactBps(uint96 a, uint96 b, uint96 c, uint96 d, bool yesWins) public {
        (bytes32 id, uint256[4] memory s) = _setupResolved(a, b, c, d, yesWins);
        uint256 losingPool = yesWins ? (s[2] + s[3]) : (s[0] + s[1]);
        uint256 expectFee = (losingPool * engine.feeBps()) / 10_000;
        assertEq(treasury.reserves(OPS, address(collateral)), expectFee, "fee == bps*losing");

        // claim both winners; dust must be < number of winners (2)
        if (yesWins) {
            _claim(id, traders[0]);
            _claim(id, traders[1]);
        } else {
            _claim(id, traders[2]);
            _claim(id, traders[3]);
        }
        assertLe(collateral.balanceOf(address(engine)), 1, "dust < winners");
    }

    /// No winner is overpaid (each gets >= principal, total <= staked), and the
    /// winnings split is pro-rata: equal winning stakes get equal payouts.
    function testFuzz_winnersNeverOverpaid(uint96 a, uint96 b, uint96 c, uint96 d, bool yesWins)
        public
    {
        (bytes32 id, uint256[4] memory s) = _setupResolved(a, b, c, d, yesWins);
        uint256 totalStaked = s[0] + s[1] + s[2] + s[3];
        (uint256 i, uint256 j) = yesWins ? (uint256(0), uint256(1)) : (uint256(2), uint256(3));

        uint256 p0 = _claim(id, traders[i]);
        uint256 p1 = _claim(id, traders[j]);
        assertGe(p0, s[i], "winner keeps principal");
        assertGe(p1, s[j], "winner keeps principal");
        assertLe(p0 + p1, totalStaked, "winners never exceed the pot");
    }

    /// A losing stake can never be claimed, and a winner can never claim twice.
    function testFuzz_claimGuards(uint96 a, uint96 b, uint96 c, uint96 d, bool yesWins) public {
        (bytes32 id,) = _setupResolved(a, b, c, d, yesWins);
        (address winner, address loser) =
            yesWins ? (traders[0], traders[2]) : (traders[2], traders[0]);

        vm.prank(loser);
        vm.expectRevert(bytes("ENGINE: no winnings"));
        engine.claim(id);

        _claim(id, winner); // first claim ok
        vm.prank(winner);
        vm.expectRevert(bytes("ENGINE: claimed"));
        engine.claim(id);
    }

    /// An invalid market refunds every participant their full principal, exactly.
    function testFuzz_invalidRefundsPrincipal(uint96 a, uint96 b, uint96 c, uint96 d) public {
        uint256[4] memory s = _stakes(a, b, c, d);
        bytes32 id = _open();
        _take(id, traders[0], IMarketEngine.Side.Yes, s[0]);
        _take(id, traders[1], IMarketEngine.Side.Yes, s[1]);
        _take(id, traders[2], IMarketEngine.Side.No, s[2]);
        _take(id, traders[3], IMarketEngine.Side.No, s[3]);

        oracle.setOutcome(id, IOracleAdapter.Outcome.Invalid);
        vm.warp(block.timestamp + 8 days);
        engine.resolve(id);

        for (uint256 k = 0; k < 4; k++) {
            uint256 before = collateral.balanceOf(traders[k]);
            uint256 refund = _claim(id, traders[k]);
            assertEq(refund, s[k], "refund == principal");
            assertEq(collateral.balanceOf(traders[k]) - before, s[k], "balance restored");
        }
        assertEq(collateral.balanceOf(address(engine)), 0, "engine emptied on refund");
    }
}
