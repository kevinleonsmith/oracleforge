// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MiniTest} from "./utils/MiniTest.sol";
import {Deploy} from "../script/Deploy.s.sol";
import {MarketEngine} from "../src/MarketEngine.sol";
import {ScalarMarketEngine} from "../src/ScalarMarketEngine.sol";
import {CategoricalMarketEngine} from "../src/CategoricalMarketEngine.sol";
import {ChainlinkOracleAdapter} from "../src/oracle/ChainlinkOracleAdapter.sol";
import {ScalarChainlinkAdapter} from "../src/oracle/ScalarChainlinkAdapter.sol";
import {CategoricalChainlinkAdapter} from "../src/oracle/CategoricalChainlinkAdapter.sol";
import {ForgeGovernor} from "../src/ForgeGovernor.sol";
import {Treasury} from "../src/Treasury.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";

/// @notice Runs the real deployment script under `forge test` (the broadcast
///         cheatcode shims no-op outside `forge script`) and asserts the whole
///         topology is wired: all three engines up, each bound one-to-one to its
///         own oracle adapter, all sharing the single Treasury and collateral,
///         with the governor set to the deployer. Guards against a half-wired
///         deploy (e.g. an engine pointing at the wrong oracle, or an adapter left
///         unbound) before it ever reaches a testnet.
contract DeployTest is MiniTest {
    Deploy internal deploy;

    function setUp() public {
        deploy = new Deploy();
        deploy.run(); // governor (admin) becomes this test contract (msg.sender in run)
    }

    /// Every contract in the book is a real, distinct deployment (nothing zero).
    function test_allContractsDeployed() public view {
        address[10] memory addrs = [
            deploy.token(),
            deploy.treasury(),
            deploy.binaryOracle(),
            deploy.binaryEngine(),
            deploy.scalarOracle(),
            deploy.scalarEngine(),
            deploy.categoricalOracle(),
            deploy.categoricalEngine(),
            deploy.governor(),
            deploy.collateral()
        ];
        for (uint256 i; i < addrs.length; i++) {
            assertTrue(addrs[i] != address(0), "address is zero");
            assertTrue(addrs[i].code.length > 0 || addrs[i] == deploy.collateral(), "no code");
        }
    }

    /// Each engine points at its *own* oracle adapter, and each adapter is bound
    /// back to that same engine (the one-to-one initEngine binding).
    function test_eachEngineBoundToItsOracle() public view {
        MarketEngine be = MarketEngine(deploy.binaryEngine());
        ScalarMarketEngine se = ScalarMarketEngine(deploy.scalarEngine());
        CategoricalMarketEngine ce = CategoricalMarketEngine(deploy.categoricalEngine());

        assertEq(address(be.oracle()), deploy.binaryOracle(), "binary engine -> binary oracle");
        assertEq(address(se.oracle()), deploy.scalarOracle(), "scalar engine -> scalar oracle");
        assertEq(address(ce.oracle()), deploy.categoricalOracle(), "cat engine -> cat oracle");

        assertEq(ChainlinkOracleAdapter(deploy.binaryOracle()).engine(), deploy.binaryEngine(), "binary oracle -> engine");
        assertEq(ScalarChainlinkAdapter(deploy.scalarOracle()).engine(), deploy.scalarEngine(), "scalar oracle -> engine");
        assertEq(CategoricalChainlinkAdapter(deploy.categoricalOracle()).engine(), deploy.categoricalEngine(), "cat oracle -> engine");
    }

    /// All three engines share the one Treasury and the one collateral token.
    function test_allEnginesShareTreasuryAndCollateral() public view {
        MarketEngine be = MarketEngine(deploy.binaryEngine());
        ScalarMarketEngine se = ScalarMarketEngine(deploy.scalarEngine());
        CategoricalMarketEngine ce = CategoricalMarketEngine(deploy.categoricalEngine());

        assertEq(address(be.treasury()), deploy.treasury(), "binary treasury");
        assertEq(address(se.treasury()), deploy.treasury(), "scalar treasury");
        assertEq(address(ce.treasury()), deploy.treasury(), "cat treasury");

        assertEq(address(be.collateral()), deploy.collateral(), "binary collateral");
        assertEq(address(se.collateral()), deploy.collateral(), "scalar collateral");
        assertEq(address(ce.collateral()), deploy.collateral(), "cat collateral");
    }

    /// The governor/admin of every engine is the deployer (this test contract).
    function test_governorIsDeployer() public view {
        assertEq(MarketEngine(deploy.binaryEngine()).admin(), address(this), "binary admin");
        assertEq(ScalarMarketEngine(deploy.scalarEngine()).admin(), address(this), "scalar admin");
        assertEq(CategoricalMarketEngine(deploy.categoricalEngine()).admin(), address(this), "cat admin");
    }

    /// With no COLLATERAL env set (a testnet/demo deploy), a freely-mintable test
    /// token is deployed as the collateral, so anyone can faucet funds and trade.
    function test_demoCollateralIsDeployedAndMintable() public {
        MockERC20 col = MockERC20(deploy.collateral());
        assertTrue(address(col).code.length > 0, "collateral is a real contract");
        col.mint(address(this), 1_000e18); // public faucet
        assertEq(col.balanceOf(address(this)), 1_000e18, "minted demo collateral");
    }

    /// The three engines are distinct contracts (no accidental aliasing).
    function test_enginesAreDistinct() public view {
        assertTrue(deploy.binaryEngine() != deploy.scalarEngine(), "binary != scalar");
        assertTrue(deploy.scalarEngine() != deploy.categoricalEngine(), "scalar != cat");
        assertTrue(deploy.binaryEngine() != deploy.categoricalEngine(), "binary != cat");
    }

    /// The governor is deployed over the FORGE token, admin'd by the deployer, with
    /// the configured voting parameters — ready to take control via a two-step
    /// governance handover (not forced at deploy).
    function test_governorDeployedOverForgeToken() public view {
        ForgeGovernor g = ForgeGovernor(deploy.governor());
        assertEq(address(g.token()), deploy.token(), "governor votes with FORGE");
        assertEq(g.admin(), address(this), "governor admin is the deployer");
        assertTrue(g.votingPeriod() > 0, "voting period set");
        assertTrue(g.quorumVotes() > 0, "quorum set");
        // control has NOT been force-handed to the governor at deploy
        assertEq(Treasury(deploy.treasury()).governor(), address(this), "treasury still deployer-governed");
    }
}
