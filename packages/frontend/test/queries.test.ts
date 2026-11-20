// Pure logic tests. Run with: node --test --experimental-strip-types
import test from "node:test";
import assert from "node:assert/strict";

import {
  sqlOpenMarkets,
  sqlActiveProposals,
  mapMarketRow,
  mapProposalRow,
  computeStats,
} from "../lib/queries.ts";
import { bpsToPercent, formatUnits, formatCompact, impliedYesPercent, payoutPreview } from "../lib/format.ts";

test("sqlOpenMarkets filters open/closed and orders by close", () => {
  const q = sqlOpenMarkets("markets_10200_7", 25);
  assert.match(q, /FROM markets_10200_7/);
  assert.match(q, /status IN \('OPEN','CLOSED'\)/);
  assert.match(q, /ORDER BY close_at ASC LIMIT 25/);
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
