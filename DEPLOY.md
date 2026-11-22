# Deploying OracleForge to Chiado (Gnosis testnet)

This brings the whole protocol up on a public testnet and points the frontend at
it, so you have a live, wallet-connectable demo. It is **testnet only** — the
contracts are a hardened MVP but **not audited**; do not put real funds behind this.

The deploy is a single `forge script` run that brings up, in one transaction batch:
the shared `Treasury` + `ForgeToken`, all three market engines (binary / scalar /
categorical) with their Chainlink adapters, the `ForgeGovernor`, and — because no
`COLLATERAL` is set — a freely-mintable demo token (`ofUSD`) so anyone can faucet
funds and trade. (This exact pipeline is proven end-to-end against a local node in
`packages/contracts/test/Deploy.t.sol` and the devnet parity suite.)

> **Your private key never leaves your machine.** Do not paste it into any chat,
> issue, or commit. Set it as an environment variable in your own terminal only.

## 1. Prerequisites

- **Foundry** on PATH (`anvil`, `forge`, `cast`) — https://getfoundry.sh
- **A funded Chiado account.** Create a fresh key *for testnet only* and fund it
  with test xDAI from a Chiado faucet (e.g. https://faucet.chiadochain.net). You
  need only a little — the deploy costs well under 0.1 test xDAI.
- Node 20+ for the frontend.

## 2. Set env (your terminal only)

```bash
export CHIADO_RPC_URL="https://rpc.chiadochain.net"      # or your own RPC
export DEPLOYER_PK="0x<your-testnet-private-key>"        # NEVER commit or share this
# optional: export COLLATERAL=0x<token>  to use a specific ERC-20 instead of ofUSD
```

## 3. Deploy

```bash
npm run deploy:chiado
```

That runs `forge script Deploy --broadcast --rpc-url chiado --private-key $DEPLOYER_PK`.
On success it prints the deployed addresses and writes the broadcast to
`packages/contracts/broadcast/Deploy.s.sol/10200/run-latest.json`.

## 4. Wire the frontend to the deployment

```bash
npm run extract:chiado
```

This reads the broadcast and writes `packages/frontend/deployments/chiado.json`
(all nine contract addresses + the `ofUSD` demo collateral the deploy created).

## 5. Run the app against the chain

```bash
cd packages/frontend && npm install
NEXT_PUBLIC_DATA_SOURCE=chain NEXT_PUBLIC_RPC_URL="$CHIADO_RPC_URL" npm run dev
```

The UI now reads live markets/pools/positions from the index + contracts. (Sending
trades from the UI needs the wallet-connect layer — that is the next build step; see
STATUS.md "Path to a running deployment".)

## 6. Faucet the demo collateral

`ofUSD` has a public `mint`, so anyone can get play-money to trade:

```bash
cast send <ofUSD-address> "mint(address,uint256)" <your-address> 1000000000000000000000 \
  --rpc-url chiado --private-key $DEPLOYER_PK   # 1000 ofUSD
```

(The `<ofUSD-address>` is the `collateral` field in `deployments/chiado.json`.)

## Handing control to governance (optional)

The deploy leaves you (the deployer) as admin/governor of everything — the
`ForgeGovernor` is deployed but **not** yet in control. To hand the protocol to
token-holder governance (proven end-to-end in `ForgeGovernorHandover.t.sol` /
`ForgeGovernorEngineHandover.t.sol`):

1. `treasury.transferGovernor(governor)` and `engine.transferAdmin(governor)` for
   each engine (two-step nomination).
2. Pass a `ForgeGovernor` proposal that calls the matching `acceptGovernor()` /
   `acceptAdmin()` — token holders ratify the handover; the deployer can't force it.

## Before anyone deposits real money

This is a testnet demo. A mainnet launch with real funds requires, at minimum: a
**professional security audit** (these contracts are unaudited), legal/regulatory
review (a real-money prediction market is a regulated product in most
jurisdictions), and wiring the live off-chain seams (real Arweave upload, signed
Tableland mutations, the Cartesi rollup). See `docs/SECURITY-REVIEW.md` for the
internal review — which is engineering hygiene, **not** a substitute for an audit.
