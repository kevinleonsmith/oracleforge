// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {ForgeGovernor} from "../src/ForgeGovernor.sol";
import {MarketEngine} from "../src/MarketEngine.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";
import {MockOracleAdapter} from "../src/mocks/MockOracleAdapter.sol";

/// @notice End-to-end: governance takes over a market engine's admin and then
///         governs its economics. Where the Treasury-handover test proves
///         governance can move funds, this proves it controls the *protocol
///         parameters* — the fee (the protocol's revenue knob) and the dispute
///         challenge window — through proposals, after a two-step admin handover.
contract ForgeGovernorEngineHandoverTest is MiniTest {
    MockERC20 forge;
    MockERC20 collateral;
    MockOracleAdapter oracle;
    Treasury treasury;
    MarketEngine engine;
    ForgeGovernor gov;

    address deployer = address(this); // initial engine admin
    address alice = address(0xA1); // 1200 FORGE — proposer/voter

    uint64 constant PERIOD = 1 days;
    uint256 constant THRESHOLD = 100e18;
    uint256 constant QUORUM = 1000e18;

    function setUp() public {
        forge = new MockERC20("Forge", "FORGE", 18);
        forge.mint(alice, 1200e18);

        collateral = new MockERC20("USD Coin", "USDC", 18);
        oracle = new MockOracleAdapter();
        treasury = new Treasury(deployer);
        engine = new MarketEngine(address(collateral), address(oracle), address(treasury), deployer);
        gov = new ForgeGovernor(address(forge), PERIOD, THRESHOLD, QUORUM, deployer);
    }

    function _passAndExecute(address target, bytes memory data) internal returns (uint256 id) {
        vm.prank(alice);
        id = gov.propose(target, data, "govern the engine");
        vm.prank(alice);
        gov.castVote(id, true); // 1200 FORGE -> quorum + majority
        vm.warp(block.timestamp + PERIOD + 1);
        gov.execute(id);
    }

    function test_governanceTakesOverEngineAndSetsEconomics() public {
        uint16 feeBefore = engine.feeBps();

        // 1) nominate the governor as the engine's admin (two-step).
        engine.transferAdmin(address(gov));
        assertEq(engine.pendingAdmin(), address(gov), "admin nominated");

        // 2) a proposal completes the handover by calling acceptAdmin() as the governor.
        _passAndExecute(address(engine), abi.encodeWithSelector(MarketEngine.acceptAdmin.selector));
        assertEq(engine.admin(), address(gov), "engine now governed");

        // 3) the deployer can no longer tune the engine directly.
        vm.expectRevert(bytes("ENGINE: not admin"));
        engine.setFeeBps(300);

        // 4) governance raises the default fee to 3% and widens the dispute window.
        assertTrue(feeBefore != 300, "precondition: fee differs");
        _passAndExecute(address(engine), abi.encodeWithSelector(MarketEngine.setFeeBps.selector, uint16(300)));
        assertEq(engine.feeBps(), 300, "fee set by governance");

        _passAndExecute(
            address(engine), abi.encodeWithSelector(MarketEngine.setChallengeWindow.selector, uint64(2 hours))
        );
        assertEq(engine.challengeWindow(), 2 hours, "challenge window set by governance");
    }

    /// Governance can't set an out-of-range fee: the engine's own cap reverts, which
    /// surfaces as a failed execution rather than a silently-applied bad parameter.
    function test_governedFeeAboveCapRevertsExecution() public {
        engine.transferAdmin(address(gov));
        _passAndExecute(address(engine), abi.encodeWithSelector(MarketEngine.acceptAdmin.selector));

        vm.prank(alice);
        uint256 id = gov.propose(
            address(engine),
            abi.encodeWithSelector(MarketEngine.setFeeBps.selector, uint16(5000)), // > 10% cap
            "fee too high"
        );
        vm.prank(alice);
        gov.castVote(id, true);
        vm.warp(block.timestamp + PERIOD + 1);
        vm.expectRevert(bytes("GOV: exec failed")); // engine's "ENGINE: fee too high" bubbles up
        gov.execute(id);
    }
}
