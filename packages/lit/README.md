# OracleForge · Lit Protocol Integration

Token-gated / encrypted private markets. Encrypt alpha reports, private market
details, or institutional intelligence under **on-chain access conditions**; only
wallets that satisfy them can decrypt. The encrypted envelope is plain JSON, so it
archives permanently to Arweave (encrypted at rest) and indexes in Tableland.

```
 alpha report ──encrypt(conditions)──▶ envelope ──▶ Arweave (encrypted, permanent)
                "holds >= N $FORGE"        │
 reader wallet ──decrypt(authSig)──────────┘  ← only if conditions pass on-chain
```

## Access-control conditions (`conditions.ts`)

Builders produce the exact Lit ACC JSON; `evaluate` simulates what the Lit nodes
do against chain state, so gating is testable offline.

| Builder | Gate |
|---------|------|
| `forgeTokenGate({tokenAddress, minAmount})` | holds ≥ N $FORGE (ERC-20 `balanceOf`) |
| `nftGate({contractAddress})` | owns a membership NFT (ERC-721) |
| `allowlistMember({contractAddress})` | `isMember(:userAddress) == true` |
| `stakedThreshold({contractAddress, minStake})` | `stakeOf(:userAddress) >= N` |
| `and(...)` / `or(...)` | combine gates |

## Client (`litClient.ts`)

- **`MockLitClient`** — real AES-GCM encryption, gated by a simulated chain state.
  Faithful to Lit's model (the symmetric key is a function of the conditions,
  "released" only when they pass) and fully testable offline. Also tamper-evident:
  the conditions are sha256-sealed into the envelope, so an attacker can't swap in
  a weaker gate to recover the key.
- **`RealLitClient`** — wraps `@lit-protocol/*` (threshold BLS across the Lit
  network). Lazy-imported; the live path. Decryption needs the viewer's
  `sessionSigs` (a wallet signature), obtained in the browser.

```ts
import { MockLitClient, forgeTokenGate } from "@oracleforge/lit";

const lit = new MockLitClient();               // RealLitClient("datil-dev") in prod
const gate = [forgeTokenGate({ tokenAddress: FORGE, minAmount: 10n ** 18n })];
const env  = await lit.encrypt(alphaReport, gate, "xdai", { kind: "alpha", marketId });

// reader side (gated):
const text = await lit.decrypt(env, { address, state });  // or { sessionSigs } with RealLitClient
```

## Where it fits

- **Archiver** — the `EncryptedEnvelope` is JSON, so `packages/archiver` can persist
  it to Arweave as an artifact: encrypted alpha stored permanently, decryptable only
  by gated holders ("institutional intelligence vault").
- **Frontend** — a private market card calls `decrypt` in-browser with the viewer's
  wallet `sessionSigs`; non-holders see the gate, holders see the content.

## Run

```bash
npm run demo    # encrypt an alpha report, holder decrypts, non-holder denied
npm test        # conditions + gated encrypt/decrypt + tamper detection (14 tests)
```

Tests and demo run on Node alone (WebCrypto + type-stripping) — no Lit network, no
install. The live `RealLitClient` path needs `@lit-protocol/*` and a wallet.
