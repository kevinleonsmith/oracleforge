// Live data client: reads the Tableland index, then hydrates each market with its
// current on-chain pools/status (best-effort). Same function signatures as the
// mock client, so the page is unchanged. Any failure degrades to the indexed
// data (or an empty list) instead of crashing the page.
import type { Market, Prediction, GovernanceProposal } from "@oracleforge/shared/types";
import type { ScalarMarketData } from "@/components/ScalarMarketCard";
import type { CategoricalMarketData } from "@/components/CategoricalMarketCard";
import { deployment } from "./contracts";
import { readMarketOnchain, readScalarMarketOnchain, readCategoricalMarketOnchain } from "./contracts";
import { hydrateScalar, hydrateCategorical } from "./marketHydrate";
import { getScalarMarkets as mockScalarMarkets, getCategoricalMarkets as mockCategoricalMarkets } from "./mockApi";
import { queryTableland } from "./tableland";
import {
  sqlOpenMarkets, sqlLatestPrediction, sqlConfidence, sqlActiveProposals,
  mapMarketRow, mapPredictionRow, mapProposalRow, computeStats,
} from "./queries";

const BYTES32 = /^0x[0-9a-fA-F]{64}$/;

const T = deployment.tables;

export async function getOpenMarkets(): Promise<Market[]> {
  const rows = await queryTableland(sqlOpenMarkets(T.markets));
  const markets = rows.map(mapMarketRow);
  // refresh mutable fields from the chain where the market exists on-chain
  return Promise.all(
    markets.map(async (m) => {
      const live = await readMarketOnchain(m.marketId as `0x${string}`);
      return live
        ? { ...m, status: live.status, yesPool: live.yesPool, noPool: live.noPool, outcome: live.outcome }
        : m;
    })
  );
}

export async function getPrediction(marketId: string): Promise<Prediction | null> {
  const [row] = await queryTableland(sqlLatestPrediction(T.predictions, marketId));
  if (!row) return null;
  const confRows = row.id != null ? await queryTableland(sqlConfidence(T.confidence_scores, Number(row.id))) : [];
  const confidence: Record<string, number> = {};
  for (const c of confRows) confidence[String(c.source)] = Number(c.score_bps);
  return mapPredictionRow(row, confidence);
}

export async function getActiveProposals(): Promise<GovernanceProposal[]> {
  const rows = await queryTableland(sqlActiveProposals(T.governance_proposals));
  return rows.map(mapProposalRow);
}

// Scalar + categorical markets aren't indexed in Tableland yet, so the catalog
// (bands, labels) comes from the design-time defs; this refreshes each one's pools
// from its engine when the market has a real on-chain id. Any read failure degrades
// to the def, so the panels render regardless of chain state.
const dec = deployment.collateralDecimals;

export async function getScalarMarkets(): Promise<ScalarMarketData[]> {
  const defs = await mockScalarMarkets();
  return Promise.all(
    defs.map(async (d) => {
      if (!BYTES32.test(d.id)) return d;
      return hydrateScalar(d, await readScalarMarketOnchain(d.id as `0x${string}`), dec);
    })
  );
}

export async function getCategoricalMarkets(): Promise<CategoricalMarketData[]> {
  const defs = await mockCategoricalMarkets();
  return Promise.all(
    defs.map(async (d) => {
      if (!BYTES32.test(d.id)) return d;
      return hydrateCategorical(d, await readCategoricalMarketOnchain(d.id as `0x${string}`), dec);
    })
  );
}

export async function getProtocolStats() {
  const markets = await getOpenMarkets();
  const s = computeStats(markets, deployment.collateralDecimals);
  return {
    activeMarkets: s.activeMarkets,
    tvlUsd: s.tvlTokens, // collateral is a USD stable on Gnosis (WXDAI), so 1 token ~= $1
    avgConfidenceBps: s.avgProbBps,
    // oracle-node telemetry isn't on-chain in the MVP; surfaced as a constant.
    oracleNodesOnline: 46,
    oracleNodesTotal: 48,
  };
}
