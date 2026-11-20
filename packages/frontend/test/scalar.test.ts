// Pure scalar-market math. Run with: node --test --experimental-strip-types
import test from "node:test";
import assert from "node:assert/strict";

import {
  settlementFraction,
  impliedValue,
  scalarPayoutPreview,
  bandPercent,
} from "../lib/scalar.ts";

test("settlementFraction clamps into [0,1]", () => {
  assert.equal(settlementFraction(100, 200, 150), 0.5);
  assert.equal(settlementFraction(100, 200, 50), 0); // below lower
  assert.equal(settlementFraction(100, 200, 999), 1); // above upper
  assert.equal(settlementFraction(100, 200, 100), 0); // at lower
  assert.equal(settlementFraction(100, 200, 200), 1); // at upper
  assert.equal(settlementFraction(100, 100, 100), 0); // degenerate band
});

test("impliedValue reflects the pools' balance", () => {
  // balanced book -> midpoint
  assert.equal(impliedValue(100, 200, 500, 500), 150);
  // all LONG -> prices in the top of the band
  assert.equal(impliedValue(100, 200, 1000, 0), 200);
  // all SHORT -> the bottom
  assert.equal(impliedValue(100, 200, 0, 1000), 100);
  // empty book -> midpoint fallback
  assert.equal(impliedValue(100, 200, 0, 0), 150);
  // 3:1 LONG -> 75% up the band
  assert.equal(impliedValue(0, 100, 300, 100), 75);
});

test("scalarPayoutPreview: LONG wins big at the top, loses all at the bottom", () => {
  // band [0,100], existing short pool 100, stake 100 LONG, 2% fee
  const atTop = scalarPayoutPreview(0, 100, 0, 100, "LONG", 100, 100);
  assert.equal(atTop.fraction, 1);
  assert.equal(Math.round(atTop.payout), 196); // whole distributable pot
  assert.equal(Math.round(atTop.profit), 96);
  assert.ok(atTop.roi > 95 && atTop.roi < 97);

  const atBottom = scalarPayoutPreview(0, 100, 0, 100, "LONG", 100, 0);
  assert.equal(atBottom.fraction, 0);
  assert.equal(atBottom.payout, 0); // LONG gets nothing
  assert.equal(atBottom.profit, -100); // lost the whole stake

  const atMid = scalarPayoutPreview(0, 100, 0, 100, "LONG", 100, 50);
  assert.equal(atMid.fraction, 0.5);
  assert.equal(Math.round(atMid.payout), 98); // half of 196, minus fee drag
  assert.equal(Math.round(atMid.profit), -2);
});

test("scalarPayoutPreview: SHORT is the mirror", () => {
  // band [0,100], existing long pool 100, stake 100 SHORT
  const atBottom = scalarPayoutPreview(0, 100, 100, 0, "SHORT", 100, 0);
  assert.equal(Math.round(atBottom.payout), 196); // SHORT wins when it settles low
  const atTop = scalarPayoutPreview(0, 100, 100, 0, "SHORT", 100, 100);
  assert.equal(atTop.payout, 0); // SHORT gets nothing at the top
});

test("scalarPayoutPreview: zero stake is a no-op", () => {
  const p = scalarPayoutPreview(0, 100, 50, 50, "LONG", 0, 75);
  assert.equal(p.payout, 0);
  assert.equal(p.profit, 0);
  assert.equal(p.fraction, 0.75);
});

test("bandPercent positions a value on the band", () => {
  assert.equal(bandPercent(100, 200, 150), 50);
  assert.equal(bandPercent(0, 100, 30), 30);
  assert.equal(bandPercent(100, 200, 10), 0); // clamped
});
