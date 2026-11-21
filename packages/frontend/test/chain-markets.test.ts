// Pure scalar/categorical on-chain decode + hydrate. Run with:
//   node --test --experimental-strip-types
import test from "node:test";
import assert from "node:assert/strict";

import { decodeScalarMarket, decodeCategoricalMarket } from "../lib/marketDecode.ts";
import { baseUnitsToTokens, hydrateScalar, hydrateCategorical } from "../lib/marketHydrate.ts";

test("decodeScalarMarket maps the tuple and gates settledValue on RESOLVED", () => {
  const open = decodeScalarMarket({
    createdAt: 100n, status: 0, lower: -50n, upper: 150n,
    longPool: 1000n, shortPool: 500n, settledValue: 0n,
  });
  assert.equal(open?.status, "OPEN");
  assert.equal(open?.lower, "-50");
  assert.equal(open?.upper, "150");
  assert.equal(open?.longPool, "1000");
  assert.equal(open?.shortPool, "500");
  assert.equal(open?.settledValue, undefined); // not RESOLVED

  const resolved = decodeScalarMarket({
    createdAt: 100n, status: 2, lower: 0n, upper: 100n,
    longPool: 1n, shortPool: 1n, settledValue: 42n,
  });
  assert.equal(resolved?.status, "RESOLVED");
  assert.equal(resolved?.settledValue, "42");
});

test("decodeScalarMarket returns null for a nonexistent market", () => {
  assert.equal(
    decodeScalarMarket({ createdAt: 0n, status: 0, lower: 0n, upper: 1n, longPool: 0n, shortPool: 0n, settledValue: 0n }),
    null
  );
});

test("decodeCategoricalMarket maps pools and gates winningOutcome on RESOLVED", () => {
  const open = decodeCategoricalMarket({
    createdAt: 100n, status: 0, outcomeCount: 3, winningOutcome: 0,
    pools: [600n, 400n, 0n],
  });
  assert.equal(open?.status, "OPEN");
  assert.equal(open?.outcomeCount, 3);
  assert.deepEqual(open?.pools, ["600", "400", "0"]);
  assert.equal(open?.winningOutcome, undefined);

  const resolved = decodeCategoricalMarket({
    createdAt: 100n, status: 2, outcomeCount: 3, winningOutcome: 1, pools: [600n, 400n, 0n],
  });
  assert.equal(resolved?.status, "RESOLVED");
  assert.equal(resolved?.winningOutcome, 1);

  assert.equal(
    decodeCategoricalMarket({ createdAt: 0n, status: 0, outcomeCount: 2, winningOutcome: 0, pools: [] }),
    null
  );
});

test("baseUnitsToTokens divides by 10^decimals, 0 for malformed input", () => {
  assert.equal(baseUnitsToTokens(1_000_000_000_000_000_000n, 18), 1); // 1e18 wei -> 1 token
  assert.equal(baseUnitsToTokens("2500000", 6), 2.5); // 6-decimal stable
  assert.equal(baseUnitsToTokens("0", 18), 0);
  assert.equal(baseUnitsToTokens("not-a-number", 18), 0);
});

test("hydrateScalar refreshes the pools and leaves the def on a null read", () => {
  const def = { id: "m", category: "CRYPTO", question: "q", feed: "ETH/USD", lower: 0, upper: 100, unit: "$", longPool: 1, shortPool: 1 };
  assert.equal(hydrateScalar(def, null, 18), def); // no-op

  const live = { status: "OPEN" as const, lower: "0", upper: "100", longPool: "3000000", shortPool: "1000000" };
  const h = hydrateScalar(def, live, 6);
  assert.equal(h.longPool, 3); // 3e6 / 1e6
  assert.equal(h.shortPool, 1);
  assert.equal(h.lower, 0); // band untouched
  assert.equal(h.unit, "$"); // label untouched
});

test("hydrateCategorical refreshes pools by index, keeps labels and extra outcomes", () => {
  const def = {
    id: "m", category: "GEO", question: "q", feed: "F",
    outcomes: [{ label: "A", pool: 1 }, { label: "B", pool: 1 }, { label: "C", pool: 1 }],
  };
  assert.equal(hydrateCategorical(def, null, 18), def); // no-op

  // chain read covers only the first two outcomes
  const live = { status: "OPEN" as const, outcomeCount: 3, pools: ["5000000", "1000000"] };
  const h = hydrateCategorical(def, live, 6);
  assert.deepEqual(h.outcomes.map((o) => o.pool), [5, 1, 1]); // third keeps its def value
  assert.deepEqual(h.outcomes.map((o) => o.label), ["A", "B", "C"]); // labels untouched
});
