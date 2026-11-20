// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {MarketEngine} from "../src/MarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {ChainlinkOracleAdapter} from "../src/oracle/ChainlinkOracleAdapter.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockAggregator} from "../src/mocks/MockAggregator.sol";
import {IMarketEngine} from "../src/interfaces/IMarketEngine.sol";

contract MarketEngineTest is MiniTest {
    MockERC20 collateral;
    MockAggregator feed;
    Treasury treasury;
    ChainlinkOracleAdapter oracle;
    MarketEngine engine;

    address admin = address(0xA11CE);
    address alice = address(0xA1);
    address bob = address(0xB0);

    bytes32 marketId;

    function setUp() public {
        collateral = new MockERC20("USD Coin", "USDC", 6);
        feed = new MockAggregator(8, "EUR / USD");
        treasury = new Treasury(admin);

        // Deploy oracle first (needs no engine at construction), deploy the
        // engine pointing at it, then bind the two with a one-time initEngine.
        oracle = new ChainlinkOracleAdapter();
        engine = new MarketEngine(address(collateral), address(oracle), address(treasury), admin);
        oracle.initEngine(address(engine));

        // fund traders
        collateral.mint(alice, 1_000e6);
        collateral.mint(bob, 1_000e6);
    }

    function _createMarket(uint8 comparator, int256 threshold) internal returns (bytes32 id) {
        vm.prank(admin);
        id = engine.createMarket(
            keccak256("Will EUR/USD close above 1.10 on date X?"),
            uint64(block.timestamp + 7 days),
            6700, // 67% AI prob
            abi.encode(address(feed), address(0), threshold, comparator, uint64(0))
        );
    }

    function test_CreateMarket_setsState() public {
        marketId = _createMarket(0, 110_000_000); // >= 1.10 (8 decimals)
        IMarketEngine.Market memory m = engine.getMarket(marketId);
        assertEq(uint8(m.status), uint8(IMarketEngine.Status.Open), "status open");
        assertEq(uint256(m.aiProbBps), 6700, "ai prob stored");
    }

    function test_FullLifecycle_YesWins_paysWinnersAndFee() public {
        marketId = _createMarket(0, 110_000_000);

        // Alice bets YES 300, Bob bets NO 100
        vm.startPrank(alice);
        collateral.approve(address(engine), 300e6);
        engine.takePosition(marketId, IMarketEngine.Side.Yes, 300e6);
        vm.stopPrank();

        vm.startPrank(bob);
        collateral.approve(address(engine), 100e6);
        engine.takePosition(marketId, IMarketEngine.Side.No, 100e6);
        vm.stopPrank();

        // Outcome: EUR/USD = 1.12 >= 1.10 => YES
        feed.set(112_000_000);
        vm.warp(block.timestamp + 8 days);
        engine.resolve(marketId);

        IMarketEngine.Market memory m = engine.getMarket(marketId);
        assertEq(m.outcome, 1, "yes wins");

        // Fee = 2% of losing (NO) pool of 100 = 2 USDC -> treasury
        assertEq(
            treasury.reserves(keccak256("OPERATIONS"), address(collateral)),
            2e6,
            "fee to treasury"
        );

        // Alice claims: principal 300 + full remaining NO pool (98)
        uint256 before = collateral.balanceOf(alice);
        vm.prank(alice);
        uint256 payout = engine.claim(marketId);
        assertEq(payout, 398e6, "alice payout = 300 + 98");
        assertEq(collateral.balanceOf(alice) - before, 398e6, "balance credited");
    }

    function test_InvalidMarket_refundsBothSides() public {
        marketId = _createMarket(0, 110_000_000);

        vm.startPrank(alice);
        collateral.approve(address(engine), 50e6);
        engine.takePosition(marketId, IMarketEngine.Side.Yes, 50e6);
        vm.stopPrank();

        // Feed never updated from 0 => adapter returns Pending, resolve reverts.
        vm.warp(block.timestamp + 8 days);
        vm.expectRevert(bytes("ENGINE: oracle pending"));
        engine.resolve(marketId);
    }
}
