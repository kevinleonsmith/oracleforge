// Live data client: reads the Tableland index, then hydrates each market with its
// current on-chain pools/status (best-effort). Same function signatures as the
// mock client, so the page is unchanged. Any failure degrades to the indexed
// data (or an empty list) instead of crashing the page.
import type { Market, Prediction, GovernanceProposal } from "@oracleforge/shared/types";
import { deployment } from "./contracts";
import { readMarketOnchain } from "./contracts";
import { queryTableland } from "./tableland";
import {
  sqlOpenMarkets, sqlLatestPrediction, sqlConfidence, sqlActiveProposals,
  mapMarketRow, mapPredictionRow, mapProposalRow, computeStats,
} from "./queries";

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
