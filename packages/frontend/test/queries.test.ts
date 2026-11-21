// Pure logic tests. Run with: node --test --experimental-strip-types
import test from "node:test";
import assert from "node:assert/strict";

import {
  sqlOpenMarkets,
  sqlActiveProposals,
  sqlScalarMarkets,
  sqlCategoricalMarkets,
  mapMarketRow,
  mapProposalRow,
  mapScalarMarketRow,
  mapCategoricalMarketRow,
  computeStats,
  computeProtocolStats,
} from "../lib/queries.ts";
import { bpsToPercent, formatUnits, formatCompact, impliedYesPercent, payoutPreview } from "../lib/format.ts";

test("sqlOpenMarkets filters open/closed and orders by close", () => {
  const q = sqlOpenMarkets("markets_10200_7", 25);
  assert.match(q, /FROM markets_10200_7/);
  assert.match(q, /status IN \('OPEN','CLOSED'\)/);
  assert.match(q, /ORDER BY close_at ASC LIMIT 25/);
});

test("sqlScalarMarkets / sqlCategoricalMarkets filter by market_type", () => {
  const sc = sqlScalarMarkets("markets_10200_7", 10);
  assert.match(sc, /FROM markets_10200_7/);
  assert.match(sc, /market_type='scalar'/);
  assert.match(sc, /status IN \('OPEN','CLOSED'\)/);
  assert.match(sc, /LIMIT 10/);
  assert.match(sc, /params/); // selects the type-specific params blob

  const cat = sqlCategoricalMarkets("markets_10200_7");
  assert.match(cat, /market_type='categorical'/);
});

test("mapScalarMarketRow parses the band/unit/feed from params", () => {
  const def = mapScalarMarketRow({
    market_id: "0xMKT", question: "ETH close?", category: "CRYPTO",
    market_type: "scalar",
    params: JSON.stringify({ feed: "ETH/USD", lower: 3000, upper: 5000, unit: "$" }),
  });
  assert.equal(def.id, "0xMKT");
  assert.equal(def.feed, "ETH/USD");
  assert.equal(def.lower, 3000);
  assert.equal(def.upper, 5000);
  assert.equal(def.unit, "$");
  assert.equal(def.longPool, 0); // hydrated live later
  assert.equal(def.shortPool, 0);
});

test("mapScalarMarketRow tolerates a malformed params blob", () => {
  const def = mapScalarMarketRow({ market_id: "0x1", question: "q", category: "MACRO", params: "not json" });
  assert.equal(def.lower, 0);
  assert.equal(def.upper, 0);
  assert.equal(def.feed, "");
});

test("mapCategoricalMarketRow parses outcome labels from params", () => {
  const def = mapCategoricalMarketRow({
    market_id: "0xCAT", question: "Who wins?", category: "GEO",
    params: JSON.stringify({ feed: "FUNCTIONS/ELECTION", outcome_count: 3, outcomes: ["A", "B", "C"] }),
  });
  assert.equal(def.feed, "FUNCTIONS/ELECTION");
  assert.deepEqual(def.outcomes.map((o) => o.label), ["A", "B", "C"]);
  assert.deepEqual(def.outcomes.map((o) => o.pool), [0, 0, 0]);
});

test("mapCategoricalMarketRow falls back to generic labels from outcome_count", () => {
  const def = mapCategoricalMarketRow({
    market_id: "0x1", question: "q", category: "MACRO",
    params: JSON.stringify({ outcome_count: 2 }), // labels not stored
  });
  assert.deepEqual(def.outcomes.map((o) => o.label), ["Outcome 1", "Outcome 2"]);
});

test("sqlActiveProposals selects active", () => {
  assert.match(sqlActiveProposals("gov"), /status='ACTIVE'/);
});

test("mapMarketRow snake_case -> camelCase domain object", () => {
  const m = mapMarketRow({
    market_id: "0xabc", question: "Q?", question_hash: "0x1", category: "MACRO",
    status: "OPEN", ai_prob_bps: "6700", yes_pool: "5800000", no_pool: "2900000",
    outcome: null, created_at: "1737000000", close_at: "1740800000", arweave_tx: null,
  });
  assert.equal(m.marketId, "0xabc");
  assert.equal(m.aiProbBps, 6700);
  assert.equal(m.yesPool, "5800000");
  assert.equal(m.outcome, undefined);
  assert.equal(m.arweaveTx, undefined);
  assert.equal(m.closeAt, 1740800000);
});

test("mapProposalRow maps vote tallies", () => {
  const p = mapProposalRow({
    proposal_id: "OFP-47", title: "T", status: "ACTIVE",
    for_votes: "72", against_votes: "19", abstain_votes: "9",
    quorum_bps: "6800", opens_at: "1", closes_at: "2",
  });
  assert.equal(p.proposalId, "OFP-47");
  assert.equal(p.forVotes, "72");
  assert.equal(p.quorumBps, 6800);
});

test("computeStats sums pools (18-decimals) and averages prob", () => {
  const mk = (yes: string, no: string, bps: number) =>
    mapMarketRow({ market_id: "x", yes_pool: yes, no_pool: no, ai_prob_bps: bps, status: "OPEN" });
  const one = "1000000000000000000"; // 1 token, 18 decimals
  const stats = computeStats([mk(one, one, 6000), mk(one, "0", 4000)], 18);
  assert.equal(stats.activeMarkets, 2);
  assert.equal(stats.tvlTokens, 3); // 1+1 + 1+0
  assert.equal(stats.avgProbBps, 5000);
});

test("computeStats handles empty", () => {
  assert.deepEqual(computeStats([], 18), { activeMarkets: 0, tvlTokens: 0, avgProbBps: 0 });
});

test("computeProtocolStats aggregates TVL + count across all three market types", () => {
  const one = "1000000000000000000"; // 1 token, 18 decimals
  const binary = [
    mapMarketRow({ market_id: "b", yes_pool: one, no_pool: one, ai_prob_bps: 6000, status: "OPEN" }),
  ];
  const scalar = [
    mapScalarMarketRow({ market_id: "s", params: JSON.stringify({ lower: 0, upper: 10 }) }),
  ];
  scalar[0].longPool = 5;
  scalar[0].shortPool = 3;
  const categorical = [
    mapCategoricalMarketRow({ market_id: "c", params: JSON.stringify({ outcome_count: 2 }) }),
  ];
  categorical[0].outcomes = [{ label: "A", pool: 4 }, { label: "B", pool: 6 }];

  const s = computeProtocolStats(binary, scalar, categorical, 18);
  assert.equal(s.activeMarkets, 3); // 1 + 1 + 1
  assert.equal(s.tvlTokens, 20); // binary 2 + scalar 8 + categorical 10
  assert.equal(s.avgProbBps, 6000); // binary-only average
});

test("computeProtocolStats: avg confidence is binary-only, zero when no binary", () => {
  const scalar = [mapScalarMarketRow({ market_id: "s", params: JSON.stringify({ lower: 0, upper: 1 }) })];
  scalar[0].longPool = 2;
  scalar[0].shortPool = 2;
  const s = computeProtocolStats([], scalar, [], 18);
  assert.equal(s.activeMarkets, 1);
  assert.equal(s.tvlTokens, 4);
  assert.equal(s.avgProbBps, 0); // no binary markets -> no confidence figure
});

test("format helpers", () => {
  assert.equal(bpsToPercent(6700), 67);
  assert.equal(formatUnits("2500000", 6), 2.5);
  assert.equal(formatCompact(48_700_000), "$48.7M");
  assert.equal(impliedYesPercent("3", "1"), 75);
  assert.equal(impliedYesPercent("0", "0"), 50);
});

test("payoutPreview matches parimutuel settlement (2% fee)", () => {
  // YES pool 300, NO pool 100, stake 300 on YES:
  // winnings = 300/(300+300) * 100 * 0.98 = 49; payout = 349
  const p = payoutPreview(300, 100, "YES", 300);
  assert.equal(Math.round(p.profit), 49);
  assert.equal(Math.round(p.payout), 349);
  assert.ok(p.roi > 16 && p.roi < 17); // 49/300 ~= 16.3%
  // zero stake -> just the current implied price, no payout
  const z = payoutPreview(300, 100, "YES", 0);
  assert.equal(z.payout, 0);
  assert.equal(Math.round(z.pricePct), 75);
});
