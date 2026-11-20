// viem bindings for the OracleForge contracts on Gnosis/Chiado. Reads market
// state live from the chain; the ABI fragments are the minimal set the UI needs.
import { createPublicClient, http, type Address } from "viem";
import { gnosis, gnosisChiado } from "viem/chains";
import { getDeployment, isDeployed } from "./addresses";

export const CHAIN = process.env.NEXT_PUBLIC_CHAIN === "gnosis" ? gnosis : gnosisChiado;
export const deployment = getDeployment(CHAIN.id);
export const deployed = isDeployed(deployment);

export const publicClient = createPublicClient({
  chain: CHAIN,
  transport: http(process.env.NEXT_PUBLIC_RPC_URL),
});

export const marketEngineAbi = [
  {
    type: "function", name: "getMarket", stateMutability: "view",
    inputs: [{ name: "marketId", type: "bytes32" }],
    outputs: [{
      name: "", type: "tuple",
      components: [
        { name: "questionHash", type: "bytes32" },
        { name: "createdAt", type: "uint64" },
        { name: "closeAt", type: "uint64" },
        { name: "aiProbBps", type: "uint16" },
        { name: "feeBps", type: "uint16" },
        { name: "status", type: "uint8" },
        { name: "outcome", type: "uint8" },
        { name: "yesPool", type: "uint256" },
        { name: "noPool", type: "uint256" },
      ],
    }],
  },
  { type: "function", name: "feeBps", stateMutability: "view", inputs: [], outputs: [{ name: "", type: "uint16" }] },
  // --- optimistic resolution / dispute window ---
  { type: "function", name: "challengeWindow", stateMutability: "view", inputs: [], outputs: [{ name: "", type: "uint64" }] },
  { type: "function", name: "disputeBond", stateMutability: "view", inputs: [], outputs: [{ name: "", type: "uint256" }] },
  { type: "function", name: "proposedAt", stateMutability: "view", inputs: [{ name: "", type: "bytes32" }], outputs: [{ name: "", type: "uint64" }] },
  { type: "function", name: "proposedOutcome", stateMutability: "view", inputs: [{ name: "", type: "bytes32" }], outputs: [{ name: "", type: "uint8" }] },
  { type: "function", name: "challengerOf", stateMutability: "view", inputs: [{ name: "", type: "bytes32" }], outputs: [{ name: "", type: "address" }] },
  {
    type: "function", name: "takePosition", stateMutability: "nonpayable",
    inputs: [
      { name: "marketId", type: "bytes32" },
      { name: "side", type: "uint8" },
      { name: "amount", type: "uint256" },
    ],
    outputs: [],
  },
  {
    type: "function", name: "claim", stateMutability: "nonpayable",
    inputs: [{ name: "marketId", type: "bytes32" }],
    outputs: [{ name: "payout", type: "uint256" }],
  },
  // dispute() posts `disputeBond` collateral; finalize() locks a proposal in
  { type: "function", name: "dispute", stateMutability: "nonpayable", inputs: [{ name: "marketId", type: "bytes32" }], outputs: [] },
  { type: "function", name: "finalize", stateMutability: "nonpayable", inputs: [{ name: "marketId", type: "bytes32" }], outputs: [] },
] as const;

const STATUS = ["OPEN", "CLOSED", "RESOLVED", "INVALID"] as const;

export interface OnchainMarket {
  status: (typeof STATUS)[number];
  aiProbBps: number;
  feeBps: number;
  yesPool: string;
  noPool: string;
  outcome?: 0 | 1;
}

/** Live read of a single market's mutable state (pools/status). */
export async function readMarketOnchain(marketId: `0x${string}`): Promise<OnchainMarket | null> {
  if (!deployed) return null;
  try {
    const m = await publicClient.readContract({
      address: deployment.contracts.MarketEngine as Address,
      abi: marketEngineAbi,
      functionName: "getMarket",
      args: [marketId],
    });
    if (m.createdAt === 0n) return null; // market doesn't exist
    const status = STATUS[m.status] ?? "OPEN";
    return {
      status,
      aiProbBps: m.aiProbBps,
      feeBps: m.feeBps,
      yesPool: m.yesPool.toString(),
      noPool: m.noPool.toString(),
      outcome: status === "RESOLVED" ? ((m.outcome ? 1 : 0) as 0 | 1) : undefined,
    };
  } catch {
    return null; // RPC hiccup -> caller keeps the indexed row
  }
}

/** Raw on-chain fields the optimistic-resolution phase (lib/dispute) is derived
 *  from. The engine-wide window/bond are market-independent; the per-market
 *  fields only matter while a market sits in `CLOSED` (outcome proposed). */
export interface OnchainDispute {
  challengeWindow: number; // seconds; 0 => instant settlement, no dispute phase
  disputeBond: string; // collateral a challenger must bond (base units)
  proposedAt: number; // unix seconds the outcome was proposed
  proposedOutcome: number; // IOracleAdapter.Outcome ordinal
  challenger: string; // challengerOf; zero address if undisputed
}

/** Live read of a market's dispute-window state (engine window + per-market
 *  proposal). Returns null off-chain or on an RPC hiccup. */
export async function readDisputeState(marketId: `0x${string}`): Promise<OnchainDispute | null> {
  if (!deployed) return null;
  const engine = deployment.contracts.MarketEngine as Address;
  try {
    const [challengeWindow, disputeBond, proposedAt, proposedOutcome, challenger] =
      await Promise.all([
        publicClient.readContract({ address: engine, abi: marketEngineAbi, functionName: "challengeWindow" }),
        publicClient.readContract({ address: engine, abi: marketEngineAbi, functionName: "disputeBond" }),
        publicClient.readContract({ address: engine, abi: marketEngineAbi, functionName: "proposedAt", args: [marketId] }),
        publicClient.readContract({ address: engine, abi: marketEngineAbi, functionName: "proposedOutcome", args: [marketId] }),
        publicClient.readContract({ address: engine, abi: marketEngineAbi, functionName: "challengerOf", args: [marketId] }),
      ]);
    return {
      challengeWindow: Number(challengeWindow),
      disputeBond: disputeBond.toString(),
      proposedAt: Number(proposedAt),
      proposedOutcome: Number(proposedOutcome),
      challenger: challenger as string,
    };
  } catch {
    return null;
  }
}
