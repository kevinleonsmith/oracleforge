# OracleForge — Contract Security Review

_Reviewed 2026-11-20 · scope: `packages/contracts/src` (MarketEngine, Treasury,
ForgeToken, ERC20, ChainlinkOracleAdapter) · internal review, **not an audit**._

A read-through of the on-chain value path for the classic failure modes:
reentrancy, access control, arithmetic/rounding, fund-locking, oracle trust, and
privileged-role risk. The engine is well-constrained by the test suite (unit +
512-run settlement fuzz + stateful solvency invariants + live-node parity); this
pass looks for what those don't assert.

## Findings

| # | Severity | Status | Summary |
|---|----------|--------|---------|
| F1 | **High** | **Fixed** | No-winner market stranded the losing pool permanently |
| F2 | Medium | **Fixed** | Fee is read at resolve time, not fixed at market creation |
| F3 | Low | **Fixed** | Single-shot oracle read, no dispute/challenge window |
| F4 | Low | **Fixed** | Dead `Status.Closed` state (never set) — now the proposed state |
| F5 | Low | Documented | No admin rotation; admin-key loss is unrecoverable |
| F6 | Info | Documented | Constructor missing zero-address checks |
| F7 | Info | Verified safe | No `ReentrancyGuard` (sound today via CEI + trusted token) |

### F1 — No-winner market stranded the losing pool _(High, fixed)_

`MarketEngine.claim()` pays winners `stake + stake * losingPool / winningPool`,
with `winningPool` as the denominator. If every participant stakes the **losing**
side (e.g. all bet NO, the oracle resolves YES), `resolve()` still marked the
market `Resolved` with `winningPool == 0`. No winner exists, so `claim()` reverts
`ENGINE: no winnings` for everyone, and the entire losing pool (minus the fee
already skimmed) sits in the contract **with no code path that can ever move it**.

- **Trigger:** unprivileged and realistic — any market that resolves against a
  one-sided book. No special role needed.
- **Why the invariants missed it:** the stateful suite proves
  `balance + payouts + fees == deposits`. Stranded funds count as *balance*, so
  conservation still held while the money was unspendable. Conservation is not
  liveness.
- **Fix** (`MarketEngine.resolve`): if the winning pool is empty, the market is a
  push — mark it `Invalid` and skip the fee, so every participant is refunded
  their principal through the existing invalid-refund path and the engine empties.
- **Regression:** `test_noWinnerMarket_refundsLosingSide` in `MarketEngineFuzz.t.sol`
  (all NO, resolves YES → no fee, both refunded, engine balance 0).

### F2 — Fee is read at resolve time, not fixed at creation _(Medium, fixed)_

`resolve()` applied the **current** `feeBps`. `admin` could call `setFeeBps` (up to
the 10% cap) at any time, including after positions are taken but before
resolution, changing the economics bettors agreed to. `admin` is a trusted role
(it already authorizes relayers), so this was privileged-role risk rather than an
open exploit, but the fee a market settles at should be fixed when the market
opens.

- **Fix:** `feeBps` is now snapshotted into the `Market` struct at `createMarket`
  and `resolve()` reads `m.feeBps`; the global `feeBps` is now only the default
  applied to **new** markets. The `getMarket` tuple gained a field, so the viem
  ABI and `OnchainMarket` type in `packages/frontend/lib/contracts.ts` were updated
  in lockstep (only named-field decoders read the tuple, so nothing else moved).
- **Regression:** `test_feeIsFixedAtCreation_notResolve` in `MarketEngineFuzz.t.sol`
  (open at 2%, admin hikes the global to 10%, resolve still skims the market's
  original 2%).

### F3 — Single-shot oracle read, no dispute window _(Low, fixed)_

`resolve()` used to read the oracle **once**, at whatever block the first caller
picked after `closeAt`, and finalize immediately — no period to contest a bad or
transient read near a threshold.

- **Fix:** optimistic resolution with a bonded dispute window. With a nonzero
  `challengeWindow`, `resolve()` only *proposes* the oracle's outcome (status
  `Closed`); `finalize()` locks it in once the window elapses, and anyone can
  `dispute()` within the window by posting `disputeBond` collateral. A dispute
  freezes finalization until the admin `arbitrate()`s: an upheld challenge refunds
  the bond and the admin's ruling becomes authoritative, a rejected one forfeits
  the bond to the treasury and the proposed outcome stands. The default
  `challengeWindow == 0` preserves instant settlement, so the window is opt-in and
  strictly additive. Covered by `MarketEngineDispute.t.sol` (5 tests).
- **Still MVP-shaped:** arbitration is a single trusted admin, not a decentralized
  court; a stuck dispute (admin never rules) locks the market's funds. A
  Kleros/UMA-style escalation is the production path.

### F4 — `Status.Closed` state was dead _(Low, fixed)_

The `Status` enum had `Closed` but nothing ever set it; `resolve()` went
`Open → Resolved/Invalid` directly. The dispute window (F3) gives `Closed` a real
meaning — "outcome proposed, awaiting finalization" — so the state is no longer
dead and the enum ordinals the Python/TS ports mirror are unchanged.

### F5 — No admin rotation _(Low, documented)_

`admin` is set once in the constructor with no `setAdmin`/two-step transfer. A lost
admin key means relayers can never be changed and the fee can never be adjusted.
Recommend an `Ownable2Step`-style transfer for production.

### F6 — Constructor missing zero-address checks _(Info)_

`MarketEngine`'s constructor does not reject a zero `collateral`/`oracle`/
`treasury`/`admin`. Deploy-time trust only; add `require(... != address(0))` for
defense in depth.

### F7 — No `ReentrancyGuard` _(Info, verified safe)_

`claim()` sets `claimed[marketId][msg.sender] = true` **before** the collateral
transfer (checks-effects-interactions), and `collateral` is an immutable, trusted
ERC-20 fixed at construction. A reentrant `claim` hits the `ENGINE: claimed`
guard; `takePosition` requires `Status.Open` so a resolved market can't be
re-entered to mint stake. No guard needed today — but any move to a
transfer-hooking collateral (ERC-777/-1363) would require revisiting this.

## What was checked and found sound

- **Reentrancy:** `claim()` and the invalid-refund path both follow CEI; the
  `claimed` flag is the single source of truth and is set pre-transfer.
- **Replay / id collision:** `marketId` binds `block.chainid`, so markets can't be
  replayed across chains; the `ENGINE: exists` guard blocks duplicate ids.
- **Fee accounting:** the fee is skimmed only from the losing pool (winners'
  principal untouched) and is routed to the Treasury via approve-then-pull; the
  stateful invariant proves the Treasury holds exactly the cumulative fees.
- **ERC-20:** balance-checked transfers with `unchecked` only after the check;
  the infinite-allowance (`type(uint256).max`) path is standard and safe.
- **ForgeToken:** mint is `onlyMinter` and hard-capped at `MAX_SUPPLY` on every
  path, including genesis.

_Severities are the reviewer's own and reflect an MVP that is explicitly
unaudited and not for real funds._
