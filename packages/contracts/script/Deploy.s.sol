// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ForgeToken} from "../src/ForgeToken.sol";
import {Treasury} from "../src/Treasury.sol";
import {ChainlinkOracleAdapter} from "../src/oracle/ChainlinkOracleAdapter.sol";
import {MarketEngine} from "../src/MarketEngine.sol";
import {ScalarChainlinkAdapter} from "../src/oracle/ScalarChainlinkAdapter.sol";
import {ScalarMarketEngine} from "../src/ScalarMarketEngine.sol";
import {CategoricalChainlinkAdapter} from "../src/oracle/CategoricalChainlinkAdapter.sol";
import {CategoricalMarketEngine} from "../src/CategoricalMarketEngine.sol";
import {ForgeGovernor} from "../src/ForgeGovernor.sol";

/// @notice Deployment for Gnosis Chain / Chiado testnet. Brings up the shared
///         infrastructure (Treasury + ForgeToken) and all three market engines —
///         binary, scalar, and categorical — each with its own Chainlink oracle
///         adapter, bound one-to-one via initEngine, and all sharing the one
///         Treasury and collateral.
/// @dev Run with:
///   forge script script/Deploy.s.sol:Deploy \
///     --rpc-url chiado --broadcast --private-key $DEPLOYER_PK
///
/// This is a plain contract (not forge-std's Script) so the repo builds with no
/// external library. `forge script` executes the `run()` entrypoint; wrap the
/// body in startBroadcast via the cheatcode address when broadcasting. The
/// deployed addresses are also stored in public vars so `Deploy.t.sol` can run
/// the same logic under `forge test` and assert the whole topology is wired.
contract Deploy {
    // Cheatcode handle for broadcasting (filled by forge script).
    address constant VM = 0x7109709ECfa91a80626fF3989D68f67F5b1DD12D;

    // --- deployed addresses (set by run(), read by the deployment test) ---
    address public token;
    address public treasury;
    address public collateral;

    address public binaryOracle;
    address public binaryEngine;
    address public scalarOracle;
    address public scalarEngine;
    address public categoricalOracle;
    address public categoricalEngine;
    address public governor;

    // Governance parameters (FORGE-denominated). Tunable by the governor's admin.
    uint64 constant VOTING_PERIOD = 3 days;
    uint256 constant PROPOSAL_THRESHOLD = 100_000e18; // ~0.33% of the 30M genesis
    uint256 constant QUORUM_VOTES = 1_000_000e18; // ~3.3% of genesis

    /// @return binaryEngine_ scalarEngine_ categoricalEngine_ the three engines,
    ///         sharing the Treasury and collateral recorded in the public vars.
    function run()
        external
        returns (address binaryEngine_, address scalarEngine_, address categoricalEngine_)
    {
        // governor/admin/minter default to the broadcasting EOA; swap for a
        // Gnosis Safe / timelock before mainnet.
        address gov = msg.sender;

        // Collateral is a canonical stable on Gnosis (e.g. WXDAI). Pass via env.
        address col = vmEnvAddressOr("COLLATERAL", address(0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d)); // WXDAI

        _broadcast();

        // Shared infrastructure.
        Treasury t = new Treasury(gov);
        ForgeToken f = new ForgeToken(gov, address(t), 30_000_000e18); // 30M genesis to treasury

        // Binary engine + its oracle adapter.
        ChainlinkOracleAdapter bo = new ChainlinkOracleAdapter();
        MarketEngine be = new MarketEngine(col, address(bo), address(t), gov);
        bo.initEngine(address(be));

        // Scalar (range) engine + its oracle adapter.
        ScalarChainlinkAdapter so = new ScalarChainlinkAdapter();
        ScalarMarketEngine se = new ScalarMarketEngine(col, address(so), address(t), gov);
        so.initEngine(address(se));

        // Categorical (N-outcome) engine + its oracle adapter.
        CategoricalChainlinkAdapter co = new CategoricalChainlinkAdapter();
        CategoricalMarketEngine ce = new CategoricalMarketEngine(col, address(co), address(t), gov);
        co.initEngine(address(ce));

        // On-chain governance: FORGE-weighted. Deployed ready to take control; the
        // handover is a deliberate two-step governance action, not forced at deploy:
        // the current governor/admin calls transferGovernor / transferAdmin to
        // nominate `g`, and a governance proposal that calls the matching accept*()
        // ratifies it — so token holders, not the deployer, complete the transfer.
        ForgeGovernor g = new ForgeGovernor(
            address(f), VOTING_PERIOD, PROPOSAL_THRESHOLD, QUORUM_VOTES, gov);

        _stopBroadcast();

        // Record for the deployment test and the broadcast logs.
        token = address(f);
        treasury = address(t);
        collateral = col;
        binaryOracle = address(bo);
        binaryEngine = address(be);
        governor = address(g);
        scalarOracle = address(so);
        scalarEngine = address(se);
        categoricalOracle = address(co);
        categoricalEngine = address(ce);

        return (address(be), address(se), address(ce));
    }

    // --- minimal cheatcode shims (avoid importing forge-std) ---
    function _broadcast() internal {
        (bool ok,) = VM.call(abi.encodeWithSignature("startBroadcast()"));
        ok; // ignore in non-broadcast (e.g. plain `forge test`) contexts
    }

    function _stopBroadcast() internal {
        (bool ok,) = VM.call(abi.encodeWithSignature("stopBroadcast()"));
        ok;
    }

    function vmEnvAddressOr(string memory key, address dflt) internal returns (address a) {
        (bool ok, bytes memory out) =
            VM.call(abi.encodeWithSignature("envAddress(string)", key));
        if (ok && out.length == 32) return abi.decode(out, (address));
        return dflt;
    }
}
