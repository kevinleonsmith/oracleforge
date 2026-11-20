// Shared TypeScript types — the contract between the Python generator, the
// Tableland schema, the smart contracts, and the Next.js frontend.

export type Category = "MACRO" | "CRYPTO" | "GEO" | "CLIMATE";
export type MarketStatus = "OPEN" | "CLOSED" | "RESOLVED" | "INVALID";
export enum Side {
  No = 0,
  Yes = 1,
}

/** Mirrors ChainlinkOracleAdapter.configure abi.encode layout. */
export interface OracleSpec {
  feed: string;
  fallbackFeed: string;
  threshold: string | number; // uint/int as string for big values
  comparator: 0 | 1; // 0 => answer >= threshold is YES ; 1 => <=
  maxStale: number; // seconds
}

export interface Market {
  marketId: string;
  question: string;
  questionHash: string;
  category: Category;
  status: MarketStatus;
  aiProbBps: number; // 0..10000
  yesPool: string; // uint256 decimal string
  noPool: string;
  outcome?: 0 | 1;
  createdAt: number;
  closeAt: number;
  arweaveTx?: string;
}

export interface Prediction {
  marketId: string;
  model: string;
  probYesBps: number;
  ciLowBps: number;
  ciHighBps: number;
  samples: number;
  inputHash: string;
  computedAt: number;
  confidenceBySource: Record<string, number>; // source -> 0..10000
}

export interface Position {
  marketId: string;
  account: string;
  side: Side;
  amount: string;
  claimed: boolean;
}

export interface GovernanceProposal {
  proposalId: string;
  title: string;
  status: "ACTIVE" | "PASSED" | "REJECTED" | "EXECUTED";
  forVotes: string;
  againstVotes: string;
  abstainVotes: string;
  quorumBps: number;
  opensAt: number;
  closesAt: number;
}

/** Exactly the args MarketEngine.createMarket expects (relayer call). */
export interface CreateMarketCalldata {
  questionHash: string;
  closeAt: number;
  aiProbBps: number;
  oracleParams: OracleSpec;
}

export const CONTRACT_NAMES = [
  "ForgeToken",
  "Treasury",
  "ChainlinkOracleAdapter",
  "MarketEngine",
] as const;
export type ContractName = (typeof CONTRACT_NAMES)[number];

/** Deployment address book, written by the deploy script, read by the frontend. */
export type AddressBook = Record<ContractName, `0x${string}`> & { chainId: number };
