// Data client. Today it returns mock data in the exact shape of the Tableland
// gateway + contract reads, so UI work needs no running chain. To go live,
// replace the bodies with a Tableland `Database` query and viem `readContract`
// calls — the return types (from @oracleforge/shared) do not change.
import type { Market, Prediction, GovernanceProposal } from "@oracleforge/shared/types";

const MOCK_MARKETS: Market[] = [
  {
    marketId: "0xa7f3", question: "US CPI print below 2.6% YoY for December 2026?",
    questionHash: "0x…", category: "MACRO", status: "OPEN", aiProbBps: 6700,
    yesPool: "5800000", noPool: "2900000", createdAt: 1737000000, closeAt: 1740800000,
  },
  {
    marketId: "0x9d11", question: "Will a ceasefire hold in the Eastern corridor through Jan 2027?",
    questionHash: "0x…", category: "GEO", status: "OPEN", aiProbBps: 5400,
    yesPool: "3100000", noPool: "2600000", createdAt: 1737000000, closeAt: 1742000000,
  },
  {
    marketId: "0x4c88", question: "ETH staking ratio exceeds 32% before the next hard fork?",
    questionHash: "0x…", category: "CRYPTO", status: "OPEN", aiProbBps: 4100,
    yesPool: "2400000", noPool: "3500000", createdAt: 1737000000, closeAt: 1745000000,
  },
  {
    marketId: "0x2b01", question: "Atlantic basin records ≥4 Cat-5 hurricanes in 2027 season?",
    questionHash: "0x…", category: "CLIMATE", status: "OPEN", aiProbBps: 2900,
    yesPool: "1900000", noPool: "4600000", createdAt: 1737000000, closeAt: 1751000000,
  },
];

const MOCK_PREDICTION: Record<string, Prediction> = {
  "0xa7f3": {
    marketId: "0xa7f3", model: "forge-forecast-v4", probYesBps: 6700,
    ciLowBps: 6100, ciHighBps: 7300, samples: 50000, inputHash: "0x9c…e21a",
    computedAt: 1737009000,
    confidenceBySource: { macro: 8100, news: 7600, onchain: 7100, sentiment: 6300, base: 8800 },
  },
};

const MOCK_PROPOSALS: GovernanceProposal[] = [
  {
    proposalId: "OFP-47", title: "Allocate 1.2M $FORGE to Akash GPU reserve",
    status: "ACTIVE", forVotes: "72", againstVotes: "19", abstainVotes: "9",
    quorumBps: 6800, opensAt: 1736900000, closesAt: 1737300000,
  },
];

const delay = <T,>(v: T) => new Promise<T>((r) => setTimeout(() => r(v), 60));

export async function getOpenMarkets(): Promise<Market[]> {
  return delay(MOCK_MARKETS);
}

export async function getPrediction(marketId: string): Promise<Prediction | null> {
  return delay(MOCK_PREDICTION[marketId] ?? null);
}

export async function getActiveProposals(): Promise<GovernanceProposal[]> {
  return delay(MOCK_PROPOSALS);
}

export async function getProtocolStats() {
  return delay({
    activeMarkets: 312,
    tvlUsd: 48_700_000,
    avgConfidenceBps: 7400,
    oracleNodesOnline: 46,
    oracleNodesTotal: 48,
  });
}
