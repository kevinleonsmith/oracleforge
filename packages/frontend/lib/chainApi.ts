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
  sqlScalarMarkets, sqlCategoricalMarkets,
  mapMarketRow, mapPredictionRow, mapProposalRow,
  mapScalarMarketRow, mapCategoricalMarketRow, computeProtocolStats,
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

// Scalar + categorical markets now come from the Tableland index (the relayer
// writes a self-describing row per created market: market_type + a JSON params blob
// for the band/labels). The catalog is read from there, then each market's pools are
// refreshed live from its engine. If the gateway is unavailable, degrade to the
// design-time defs so the panels still render.
const dec = deployment.collateralDecimals;

export async function getScalarMarkets(): Promise<ScalarMarketData[]> {
  let defs: ScalarMarketData[];
  try {
    const rows = await queryTableland(sqlScalarMarkets(T.markets));
    defs = rows.map(mapScalarMarketRow);
  } catch {
    return mockScalarMarkets(); // index unavailable -> design-time catalog
  }
  return Promise.all(
    defs.map(async (d) =>
      BYTES32.test(d.id) ? hydrateScalar(d, await readScalarMarketOnchain(d.id as `0x${string}`), dec) : d
    )
  );
}

export async function getCategoricalMarkets(): Promise<CategoricalMarketData[]> {
  let defs: CategoricalMarketData[];
  try {
    const rows = await queryTableland(sqlCategoricalMarkets(T.markets));
    defs = rows.map(mapCategoricalMarketRow);
  } catch {
    return mockCategoricalMarkets();
  }
  return Promise.all(
    defs.map(async (d) =>
      BYTES32.test(d.id) ? hydrateCategorical(d, await readCategoricalMarketOnchain(d.id as `0x${string}`), dec) : d
    )
  );
}

export async function getProtocolStats() {
  // Stats span all three market types: binary pools from the index, scalar +
  // categorical pools from their (index-read, engine-hydrated) catalogs.
  const [markets, scalar, categorical] = await Promise.all([
    getOpenMarkets(), getScalarMarkets(), getCategoricalMarkets(),
  ]);
  const s = computeProtocolStats(markets, scalar, categorical, deployment.collateralDecimals);
  return {
    activeMarkets: s.activeMarkets,
    tvlUsd: s.tvlTokens, // collateral is a USD stable on Gnosis (WXDAI), so 1 token ~= $1
    avgConfidenceBps: s.avgProbBps,
    // oracle-node telemetry isn't on-chain in the MVP; surfaced as a constant.
    oracleNodesOnline: 46,
    oracleNodesTotal: 48,
  };
}
