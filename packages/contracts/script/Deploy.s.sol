// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ForgeToken} from "../src/ForgeToken.sol";
import {Treasury} from "../src/Treasury.sol";
import {ChainlinkOracleAdapter} from "../src/oracle/ChainlinkOracleAdapter.sol";
import {MarketEngine} from "../src/MarketEngine.sol";

/// @notice Deployment for Gnosis Chain / Chiado testnet.
/// @dev Run with:
///   forge script script/Deploy.s.sol:Deploy \
///     --rpc-url chiado --broadcast --private-key $DEPLOYER_PK
///
/// This is a plain contract (not forge-std's Script) so the repo builds with no
/// external library. `forge script` executes the `run()` entrypoint; wrap the
/// body in startBroadcast via the cheatcode address when broadcasting.
contract Deploy {
    // Cheatcode handle for broadcasting (filled by forge script).
    address constant VM = 0x7109709ECfa91a80626fF3989D68f67F5b1DD12D;

    function run() external returns (address token, address treasury, address oracle, address engine) {
        // governor/admin/minter default to the broadcasting EOA; swap for a
        // Gnosis Safe / timelock before mainnet.
        address gov = msg.sender;

        // Collateral is a canonical stable on Gnosis (e.g. WXDAI). Pass via env.
        address collateral = vmEnvAddressOr("COLLATERAL", address(0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d)); // WXDAI

        _broadcast();

        Treasury t = new Treasury(gov);
        ForgeToken f = new ForgeToken(gov, address(t), 30_000_000e18); // 30M genesis to treasury
        ChainlinkOracleAdapter o = new ChainlinkOracleAdapter();
        MarketEngine e = new MarketEngine(collateral, address(o), address(t), gov);
        o.initEngine(address(e));

        _stopBroadcast();

        return (address(f), address(t), address(o), address(e));
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
