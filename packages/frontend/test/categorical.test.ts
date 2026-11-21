// Pure categorical-market math. Run with: node --test --experimental-strip-types
import test from "node:test";
import assert from "node:assert/strict";

import {
  impliedProbabilities,
  categoricalPayoutPreview,
  favorite,
  type CategoricalOutcome,
} from "../lib/categorical.ts";

const book = (...pools: number[]): CategoricalOutcome[] =>
  pools.map((pool, i) => ({ label: `O${i}`, pool }));

test("impliedProbabilities is each pool's share of the pot, summing to 1", () => {
  assert.deepEqual(impliedProbabilities(book(1000, 500, 500)), [0.5, 0.25, 0.25]);
  // empty book -> uniform fallback so the bars still render
  assert.deepEqual(impliedProbabilities(book(0, 0, 0)), [1 / 3, 1 / 3, 1 / 3]);
  // a single funded outcome prices at certainty
  assert.deepEqual(impliedProbabilities(book(700, 0)), [1, 0]);
  assert.deepEqual(impliedProbabilities([]), []);
});

test("categoricalPayoutPreview reproduces the docs worked example to the unit", () => {
  // Outcome 0 already holds Bob's 400; Carol 500 on 1, Dave 500 on 2.
  // Alice previews staking 600 on outcome 0 (which wins) -> 1188.
  const alice = categoricalPayoutPreview(book(400, 500, 500), 0, 600);
  assert.equal(Math.round(alice.payout), 1188);
  assert.equal(Math.round(alice.profit), 588);
  assert.equal(alice.voids, false);

  // With Alice's 600 now in outcome 0, Bob previews 400 on outcome 0 -> 792.
  const bob = categoricalPayoutPreview(book(600, 500, 500), 0, 400);
  assert.equal(Math.round(bob.payout), 792);
  assert.equal(Math.round(bob.profit), 392);
});

test("categoricalPayoutPreview: backing the underdog pays the most", () => {
  // Outcome 1 is unfunded; staking 100 on it and winning takes the whole 500 pot.
  const underdog = categoricalPayoutPreview(book(500, 0), 1, 100);
  assert.equal(Math.round(underdog.payout), 590); // 100 + 100*490/100
  assert.ok(underdog.roi > 489 && underdog.roi < 491);
  assert.equal(underdog.voids, false);
});

test("categoricalPayoutPreview: a sole funded outcome voids (push, principal back)", () => {
  const sole = categoricalPayoutPreview(book(500, 0, 0), 0, 100);
  assert.equal(sole.voids, true);
  assert.equal(sole.payout, 100); // stake returned, no winnings
  assert.equal(sole.profit, 0);
  assert.equal(sole.roi, 0);
});

test("categoricalPayoutPreview: zero / out-of-range stake is a no-op", () => {
  const zero = categoricalPayoutPreview(book(500, 500), 0, 0);
  assert.equal(zero.payout, 0);
  assert.equal(zero.profit, 0);
  assert.equal(zero.impliedProb, 0.5); // probability still reported

  const oob = categoricalPayoutPreview(book(500, 500), 9, 100);
  assert.equal(oob.payout, 0);
  assert.equal(oob.impliedProb, 0);
});

test("favorite names the largest pool, -1 for an empty book", () => {
  assert.equal(favorite(book(1000, 500, 500)), 0);
  assert.equal(favorite(book(100, 900, 300)), 1);
  assert.equal(favorite(book(0, 0, 0)), -1);
  assert.equal(favorite([]), -1);
});
