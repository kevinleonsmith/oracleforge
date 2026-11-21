// Tableland SQL builders + row -> domain mappers. Pure (no network, no enums),
// unit-tested with `node --test`. Column names match packages/shared/tableland/schema.sql.
import type { Market, Prediction, GovernanceProposal } from "@oracleforge/shared/types";
import type { ScalarMarketData } from "@/components/ScalarMarketCard";
import type { CategoricalMarketData } from "@/components/CategoricalMarketCard";

export type Row = Record<string, unknown>;

const s = (v: unknown, dflt = ""): string => (v == null ? dflt : String(v));
const n = (v: unknown, dflt = 0): number => (v == null ? dflt : Number(v));

/** Parse the markets.params JSON blob; a malformed/absent value reads as {}. */
function parseParams(v: unknown): Record<string, unknown> {
  if (v == null) return {};
  try {
    const o = JSON.parse(String(v));
    return o && typeof o === "object" ? (o as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

// ---------------------------------------------------------------- SQL builders

export function sqlOpenMarkets(table: string, limit = 50): string {
  return (
    `SELECT market_id, question, question_hash, category, status, ai_prob_bps, ` +
    `yes_pool, no_pool, outcome, created_at, close_at, arweave_tx ` +
    `FROM ${table} WHERE status IN ('OPEN','CLOSED') ORDER BY close_at ASC LIMIT ${limit}`
  );
}

/** Open scalar/categorical markets from the index, by self-describing market_type. */
function sqlTypedMarkets(table: string, marketType: string, limit: number): string {
  return (
    `SELECT market_id, question, category, market_type, params, status, created_at, close_at ` +
    `FROM ${table} WHERE market_type='${marketType}' AND status IN ('OPEN','CLOSED') ` +
    `ORDER BY close_at ASC LIMIT ${limit}`
  );
}

export function sqlScalarMarkets(table: string, limit = 50): string {
  return sqlTypedMarkets(table, "scalar", limit);
}

export function sqlCategoricalMarkets(table: string, limit = 50): string {
  return sqlTypedMarkets(table, "categorical", limit);
}

export function sqlLatestPrediction(table: string, marketId: string): string {
  return (
    `SELECT market_id, model, prob_yes_bps, ci_low_bps, ci_high_bps, samples, input_hash, computed_at ` +
    `FROM ${table} WHERE market_id='${marketId}' ORDER BY computed_at DESC LIMIT 1`
  );
}

export function sqlConfidence(table: string, predictionId: number): string {
  return `SELECT source, score_bps FROM ${table} WHERE prediction_id=${predictionId}`;
}

export function sqlActiveProposals(table: string): string {
  return (
    `SELECT proposal_id, title, status, for_votes, against_votes, abstain_votes, ` +
    `quorum_bps, opens_at, closes_at FROM ${table} WHERE status='ACTIVE' ORDER BY closes_at ASC`
  );
}

// -------------------------------------------------------------------- mappers

export function mapMarketRow(r: Row): Market {
  return {
    marketId: s(r.market_id),
    question: s(r.question),
    questionHash: s(r.question_hash),
    category: s(r.category) as Market["category"],
    status: s(r.status, "OPEN") as Market["status"],
    aiProbBps: n(r.ai_prob_bps),
    yesPool: s(r.yes_pool, "0"),
    noPool: s(r.no_pool, "0"),
    outcome: r.outcome == null ? undefined : (n(r.outcome) as 0 | 1),
    createdAt: n(r.created_at),
    closeAt: n(r.close_at),
    arweaveTx: r.arweave_tx == null ? undefined : s(r.arweave_tx),
  };
}

/** A scalar markets row -> ScalarMarketCard def. Pools start at 0 and are
 *  hydrated live from the engine (lib/marketHydrate); the band/unit/feed come
 *  from the index params the relayer wrote at createMarket. */
export function mapScalarMarketRow(r: Row): ScalarMarketData {
  const p = parseParams(r.params);
  return {
    id: s(r.market_id),
    category: s(r.category),
    question: s(r.question),
    feed: s(p.feed),
    lower: n(p.lower),
    upper: n(p.upper),
    unit: s(p.unit),
    longPool: 0,
    shortPool: 0,
  };
}

/** A categorical markets row -> CategoricalMarketCard def. Outcome labels come
 *  from the index params; a row that stored only a count falls back to generic
 *  labels. Pools start at 0 and are hydrated live from the engine. */
export function mapCategoricalMarketRow(r: Row): CategoricalMarketData {
  const p = parseParams(r.params);
  const labels = Array.isArray(p.outcomes)
    ? (p.outcomes as unknown[]).map((o) => String(o))
    : Array.from({ length: Math.max(2, n(p.outcome_count, 2)) }, (_, i) => `Outcome ${i + 1}`);
  return {
    id: s(r.market_id),
    category: s(r.category),
    question: s(r.question),
    feed: s(p.feed),
    outcomes: labels.map((label) => ({ label, pool: 0 })),
  };
}

export function mapPredictionRow(r: Row, confidence: Record<string, number> = {}): Prediction {
  return {
    marketId: s(r.market_id),
    model: s(r.model),
    probYesBps: n(r.prob_yes_bps),
    ciLowBps: n(r.ci_low_bps),
    ciHighBps: n(r.ci_high_bps),
    samples: n(r.samples),
    inputHash: s(r.input_hash),
    computedAt: n(r.computed_at),
    confidenceBySource: confidence,
  };
}

export function mapProposalRow(r: Row): GovernanceProposal {
  return {
    proposalId: s(r.proposal_id),
    title: s(r.title),
    status: s(r.status, "ACTIVE") as GovernanceProposal["status"],
    forVotes: s(r.for_votes, "0"),
    againstVotes: s(r.against_votes, "0"),
    abstainVotes: s(r.abstain_votes, "0"),
    quorumBps: n(r.quorum_bps),
    opensAt: n(r.opens_at),
    closesAt: n(r.closes_at),
  };
}

// --------------------------------------------------------------- aggregation

export interface ProtocolStats {
  activeMarkets: number;
  tvlTokens: number; // whole collateral tokens across all pools
  avgProbBps: number;
}

export function computeStats(markets: Market[], decimals: number): ProtocolStats {
  if (markets.length === 0) return { activeMarkets: 0, tvlTokens: 0, avgProbBps: 0 };
  const d = 10n ** BigInt(decimals);
  let pooled = 0n;
  let probSum = 0;
  for (const m of markets) {
    pooled += BigInt(m.yesPool || "0") + BigInt(m.noPool || "0");
    probSum += m.aiProbBps;
  }
  return {
    activeMarkets: markets.length,
    tvlTokens: Number(pooled / d),
    avgProbBps: Math.round(probSum / markets.length),
  };
}
