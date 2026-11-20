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
| F5 | Low | **Fixed** | No admin rotation; admin-key loss was unrecoverable |
| F6 | Info | **Fixed** | Constructor missing zero-address checks |
| F7 | Info | Verified safe | No `ReentrancyGuard` (sound today via CEI + trusted token) |

Every actionable finding (F1–F6) is now fixed in-tree with a regression test; F7 is
a documented no-op that holds under the current trusted-collateral assumption. The
remaining residual risk is the one called out under F3/F5 — arbitration and the
admin role are a single trusted key, the expected MVP posture, with the production
path (a decentralized court, a Safe/timelock successor) noted inline.

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

### F5 — No admin rotation _(Low, fixed)_

`admin` was set once in the constructor with no transfer path. A lost admin key
meant relayers could never be changed and the fee could never be adjusted — the
privileged role was unrecoverable.

- **Fix:** an `Ownable2Step`-style handover. `transferAdmin(newAdmin)` (onlyAdmin)
  _nominates_ a successor into `pendingAdmin` without moving the role; the nominee
  must call `acceptAdmin()` to complete it. A mistyped or dead address therefore
  never takes effect (nobody can accept it), and passing `address(0)` cancels a
  pending nomination. Relayer membership is deliberately left untouched by a
  rotation — it stays under `setRelayer` — so the handover grants exactly the admin
  role and nothing implicit.
- **Regression:** `MarketEngineAdmin.t.sol` — two-step semantics, only-admin
  nominate, only-nominee accept, cancellation, full-powers-transferred /
  old-admin-locked, and a chained third rotation.
- **Still MVP-shaped:** a single EOA admin. Production should nominate a Gnosis
  Safe / timelock as the successor — which this two-step flow already supports.

### F6 — Constructor missing zero-address checks _(Info, fixed)_

`MarketEngine`'s constructor accepted a zero `collateral`/`oracle`/`treasury`/
`admin`, any of which would brick the deployment (the first three are immutable).

- **Fix:** four `require(... != address(0))` guards at the top of the constructor,
  each with a named reason. Every real deploy path (tests, `Deploy.s.sol`, the anvil
  devnet) already passes live addresses, so the guards are purely defensive.
- **Regression:** `MarketEngineAdmin.t.sol` asserts each of the four slots reverts
  with its specific message on a zero address.

### F7 — No `ReentrancyGuard` _(Info, verified safe)_

`claim()` sets `claimed[marketId][msg.sender] = true` **before** the collateral
transfer (checks-effects-interactions), and `collateral` is an immutable, trusted
ERC-20 fixed at construction. A reentrant `claim` hits the `ENGINE: claimed`
guard; `takePosition` requires `Status.Open` so a resolved market can't be
re-entered to mint stake. No guard needed today — but any move to a
transfer-hooking collateral (ERC-777/-1363) would require revisiting this.

## Treasury & ForgeToken — focused pass

The first review scoped these two but only gave them the "found sound" summary
below; this pass audits them directly and adds the dedicated suites they lacked
(`Treasury.t.sol`, `ForgeToken.t.sol` — previously they were only exercised
indirectly through MarketEngine).

| # | Severity | Status | Summary |
|---|----------|--------|---------|
| T1 | Low | **Fixed** | Treasury had no two-step governor rotation (lost-key risk, mirrors F5) |
| T2 | Info | **Fixed** | Treasury constructor missing a zero-address governor check (mirrors F6) |
| T3 | Low | **Fixed** | Tokens sent to the Treasury outside `collectFee` were unrecoverable |
| T4 | Info | Verified safe | ForgeToken cap + minter authority (zero-minter = renounce, by design) |

### T1 — No two-step governor rotation _(Low, fixed)_

`Treasury.setGovernor` was a single-step setter: one bad call handed governance to
an unusable address, permanently bricking `allocate`/`reallocate` (the fees would
be locked). Replaced with an `Ownable2Step`-style handover —
`transferGovernor(newGovernor)` nominates, the nominee must `acceptGovernor()`, and
`address(0)` cancels a pending nomination. Same shape as the engine's F5 fix, so
both privileged roles rotate the same safe way. Regression: the governor-swap tests
in `Treasury.t.sol` (two-step, only-governor nominate, only-nominee accept, cancel,
powers-transferred / old-governor-locked).

### T2 — Constructor missing zero-address check _(Info, fixed)_

`new Treasury(address(0))` would have deployed an ungovernable treasury. Added
`require(_governor != address(0))`; the two-step transfer closes the same gap on
the mutable path (a zero nominee simply can't accept). Regression:
`test_constructor_rejectsZeroGovernor`.

### T3 — Direct transfers to the Treasury were unrecoverable _(Low, fixed)_

The Treasury credits reserve buckets only inside `collectFee`. Tokens sent to it by
a plain `transfer` (a donation, a misrouted payment, a fee path that forgot to call
`collectFee`) were never credited to any bucket, so `allocate` — which requires a
funded bucket — could never move them out. They'd sit in the contract permanently,
exactly the stranded-funds class as engine finding F1.

- **Fix:** the Treasury now keeps a `totalReserved[token]` running total alongside
  the per-bucket `reserves`, maintained on every `collectFee`/`allocate`. A new
  governor-gated `sweep(token, bucket)` credits the untracked balance
  (`balanceOf(this) - totalReserved[token]`) into a chosen bucket, making donations
  recoverable and giving a provable accounting invariant:
  `sum(reserves[*][token]) == totalReserved[token] <= balanceOf(treasury)`.
- **Regression:** `test_sweep_reconcilesDirectTransfers` (a direct deposit is swept
  into a bucket and then successfully allocated out), plus the nothing-to-sweep and
  only-governor guards.
- **Assumption:** reconciliation treats the ERC-20 as non-fee-on-transfer (the same
  trusted-collateral assumption as F7); a deflationary token could make
  `totalReserved` exceed the real balance.

### T4 — ForgeToken cap & minter authority _(Info, verified safe)_

`mint` and the constructor genesis both enforce `totalSupply + amount <= MAX_SUPPLY`
(100M), proven at the exact boundary (fills to the cap, one wei over reverts).
`mint`/`setMinter` are `onlyMinter`; rotation transfers authority cleanly. Setting
the minter to `address(0)` permanently disables minting — this is the intended way
to renounce emissions (an `EmissionsController`/timelock would hold the role in
production), so it is left unguarded by design and documented with a test rather
than "fixed." No cap, reentrancy, or authority gap found.

## ChainlinkOracleAdapter — focused pass

The adapter is the last core contract to get a direct audit and a dedicated suite
(`ChainlinkOracleAdapter.t.sol`); it was previously exercised only through the
engine's happy path. It compares a Chainlink feed's answer against a threshold with
a `>=`/`<=` comparator, behind a staleness guard and an optional fallback feed.

| # | Severity | Status | Summary |
|---|----------|--------|---------|
| O1 | Low | **Fixed** | `_read` accepted a negative feed answer (only zero was rejected) |
| O2 | Low | **Fixed** | A fallback feed with different decimals silently mis-resolved |
| O3 | Info | Documented | `maxStale == 0` disables the staleness check (foot-gun, by design) |
| O4 | Info | Documented | Threshold-scaling, never-`Invalid`, at-threshold-`YES` semantics |

### O1 — Negative feed answers were resolved, not rejected _(Low, fixed)_

`_read` rejected `answer == 0` (uninitialized) but passed a **negative** answer
through as healthy. A malfunctioning feed reporting `< 0` would then resolve a
market — and under the `<=` comparator a negative answer reads **YES** against any
positive threshold, so a glitch could settle a market the wrong way.

- **Fix:** reject `answer <= 0` in `_read`. A non-positive answer is now treated as
  unhealthy, so the adapter stays `Pending` (or tries the fallback) rather than
  settling on bad data — the same fail-safe as a stale feed.
- **Scope:** this intentionally restricts the adapter to **non-negative** data
  feeds (prices), documented in the contract header; a market on a signed feed
  needs a different adapter.
- **Regression:** `test_negativeAnswer_isPending_notResolved`, `test_zeroAnswer_isPending`.

### O2 — Fallback feed decimal mismatch _(Low, fixed)_

The same raw `threshold` is compared against whichever feed resolves. If the
`fallbackFeed` reported in different decimals than the primary (e.g. 6 vs 8), a
fallback resolution would compare against a differently-scaled number and silently
return the wrong outcome.

- **Fix:** `configure` now requires `fallbackFeed.decimals() == feed.decimals()`
  whenever a fallback is set, so the two are always directly comparable.
- **Regression:** `test_configure_rejectsFallbackDecimalMismatch`,
  `test_configure_acceptsMatchingFallbackDecimals`.

### O3 — `maxStale == 0` disables staleness _(Info, documented)_

A market configured with `maxStale == 0` accepts a feed answer of any age. This is
the intended escape hatch for feeds without a reliable heartbeat, but it removes the
only freshness guard, so it is a configuration foot-gun. Documented in the contract
header and covered by `test_zeroMaxStale_ignoresAge`; the relayer should set a
sensible `maxStale` for any heartbeat feed.

### O4 — Scaling & outcome semantics _(Info, documented)_

Three behaviours are correct-but-implicit and now documented in the contract header
and pinned by tests: (a) `threshold` must be encoded in the feed's own decimals (the
adapter does not rescale); (b) at exactly the threshold the condition reads `YES`
under both comparators; (c) this adapter never returns `Invalid` — voiding a market
is the engine's concern (e.g. a no-winner push, F1). The `onlyEngine` gating,
one-time `initEngine`, and the stay-`Pending`-on-no-healthy-feed fail-safe were all
verified sound.

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
