// Pure optimistic-resolution logic. Run with: node --test --experimental-strip-types
import test from "node:test";
import assert from "node:assert/strict";

import {
  disputePhase,
  formatCountdown,
  proposedOutcomeLabel,
  type ResolutionInput,
} from "../lib/dispute.ts";

const ZERO = "0x0000000000000000000000000000000000000000";
const CHALLENGER = "0x7F3aC9d2E1b84465A0cE9f21D8b7c0F3aE62d410";

// a proposed market mid-window by default; override per case
function mk(over: Partial<ResolutionInput> = {}): ResolutionInput {
  return {
    status: "CLOSED",
    proposedAt: 1_000_000,
    proposedOutcome: 1, // YES
    challenger: ZERO,
    challengeWindow: 3600,
    now: 1_001_000, // 1000s in, 2600s left
    ...over,
  };
}

test("proposedOutcomeLabel maps the oracle ordinals", () => {
  assert.equal(proposedOutcomeLabel(1), "YES");
  assert.equal(proposedOutcomeLabel(2), "NO");
  assert.equal(proposedOutcomeLabel(3), "VOID"); // Invalid -> void/refund
  assert.equal(proposedOutcomeLabel(0), "PENDING");
});

test("no dispute phase when the window is zero (instant settlement)", () => {
  assert.deepEqual(disputePhase(mk({ challengeWindow: 0 })), { kind: "none" });
});

test("no dispute phase unless the market is CLOSED (proposed)", () => {
  assert.deepEqual(disputePhase(mk({ status: "OPEN" })), { kind: "none" });
  assert.deepEqual(disputePhase(mk({ status: "RESOLVED" })), { kind: "none" });
});

test("inside the window -> challenge, with deadline and seconds left", () => {
  const p = disputePhase(mk());
  assert.equal(p.kind, "challenge");
  if (p.kind !== "challenge") return;
  assert.equal(p.outcome, "YES");
  assert.equal(p.deadline, 1_000_000 + 3600);
  assert.equal(p.secondsLeft, 2600);
});

test("a nonzero challenger freezes it -> disputed (even before the deadline)", () => {
  const p = disputePhase(mk({ challenger: CHALLENGER }));
  assert.equal(p.kind, "disputed");
  if (p.kind !== "disputed") return;
  assert.equal(p.challenger, CHALLENGER);
  assert.equal(p.outcome, "YES");
});

test("disputed takes precedence over an elapsed window", () => {
  // window long gone, but a dispute is open -> still frozen, not finalizable
  const p = disputePhase(mk({ now: 9_000_000, challenger: CHALLENGER }));
  assert.equal(p.kind, "disputed");
});

test("past the window with no dispute -> finalizable", () => {
  const p = disputePhase(mk({ now: 1_000_000 + 3600 }));
  assert.equal(p.kind, "finalizable");
  if (p.kind !== "finalizable") return;
  assert.equal(p.outcome, "YES");
});

test("the zero address counts as no challenger (case-insensitive)", () => {
  assert.equal(disputePhase(mk({ challenger: ZERO.toUpperCase() })).kind, "challenge");
  assert.equal(disputePhase(mk({ challenger: "" })).kind, "challenge");
});

test("formatCountdown renders h/m/s with zero padding", () => {
  assert.equal(formatCountdown(3723), "1h 02m 03s");
  assert.equal(formatCountdown(125), "2m 05s");
  assert.equal(formatCountdown(45), "45s");
  assert.equal(formatCountdown(0), "0s");
  assert.equal(formatCountdown(-10), "0s"); // clamp negatives
});
