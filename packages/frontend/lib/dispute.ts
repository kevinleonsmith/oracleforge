// Optimistic-resolution lifecycle — the pure view of MarketEngine's dispute
// window. No imports, no network: unit-tested with `node --test`. Mirrors the
// on-chain states so the same logic drives the live-chain read and the demo.
//
// On-chain, a resolved market with a nonzero `challengeWindow` goes
// Open -> Closed (outcome *proposed*) and only reaches Resolved/Invalid once
// `finalize()` runs after the window — unless someone `dispute()`s it first,
// which freezes it until the admin `arbitrate()`s. This derives, from the raw
// chain fields, which of those phases a market is in and how long is left.

/** IOracleAdapter.Outcome ordinals (Pending=0, Yes=1, No=2, Invalid=3). */
export type OutcomeLabel = "YES" | "NO" | "VOID" | "PENDING";

const ZERO_ADDR = "0x0000000000000000000000000000000000000000";

export function proposedOutcomeLabel(outcome: number): OutcomeLabel {
  switch (outcome) {
    case 1:
      return "YES";
    case 2:
      return "NO";
    case 3:
      return "VOID"; // Invalid -> market voids, principals refunded
    default:
      return "PENDING";
  }
}

export interface ResolutionInput {
  status: string; // market status: "OPEN" | "CLOSED" | "RESOLVED" | "INVALID"
  proposedAt: number; // unix seconds the outcome was proposed (0 if none)
  proposedOutcome: number; // IOracleAdapter.Outcome ordinal
  challenger: string; // challengerOf(marketId); zero address if undisputed
  challengeWindow: number; // engine-wide window, seconds (0 = instant settlement)
  now: number; // unix seconds
}

export type ResolutionPhase =
  // not in the optimistic window at all (window 0, or not a proposed market)
  | { kind: "none" }
  // outcome proposed, window still open — anyone may dispute until `deadline`
  | { kind: "challenge"; outcome: OutcomeLabel; deadline: number; secondsLeft: number }
  // a bonded dispute is open; frozen until the admin arbitrates
  | { kind: "disputed"; outcome: OutcomeLabel; challenger: string }
  // window elapsed, no dispute — anyone may finalize() to open claims
  | { kind: "finalizable"; outcome: OutcomeLabel };

function hasChallenger(addr: string): boolean {
  return !!addr && addr.toLowerCase() !== ZERO_ADDR;
}

/** Derive the optimistic-resolution phase from raw on-chain fields. */
export function disputePhase(i: ResolutionInput): ResolutionPhase {
  // Only a "proposed" market (Closed) under a nonzero window has a dispute phase.
  if (i.challengeWindow <= 0 || i.status !== "CLOSED") return { kind: "none" };

  const outcome = proposedOutcomeLabel(i.proposedOutcome);
  const deadline = i.proposedAt + i.challengeWindow;

  if (hasChallenger(i.challenger)) {
    return { kind: "disputed", outcome, challenger: i.challenger };
  }
  if (i.now < deadline) {
    return { kind: "challenge", outcome, deadline, secondsLeft: deadline - i.now };
  }
  return { kind: "finalizable", outcome };
}

/** Seconds -> compact countdown, e.g. 3723 -> "1h 02m 03s", 45 -> "45s". */
export function formatCountdown(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (x: number) => String(x).padStart(2, "0");
  if (h > 0) return `${h}h ${pad(m)}m ${pad(sec)}s`;
  if (m > 0) return `${m}m ${pad(sec)}s`;
  return `${sec}s`;
}
