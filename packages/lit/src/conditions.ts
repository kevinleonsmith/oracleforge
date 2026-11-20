// Access Control Conditions (ACCs) — the Lit-format gates for private markets,
// plus a local `evaluate` that simulates what the Lit nodes do against chain state
// (so gating is testable offline). Builders produce the exact JSON the Lit SDK
// expects; `evaluate` and `canonicalConditionsHash` are ours.
import { canonicalJson, sha256Hex } from "./crypto.ts";

export type Chain = "xdai" | "chiado" | "ethereum" | string; // Lit chain ids; Gnosis = "xdai"

export interface StandardCondition {
  contractAddress: string;
  standardContractType: "ERC20" | "ERC721" | "";
  chain: Chain;
  method: string;
  parameters: string[];
  returnValueTest: { comparator: string; value: string };
}

export interface EvmContractCondition {
  contractAddress: string;
  chain: Chain;
  functionName: string;
  functionParams: string[];
  functionAbi: Record<string, unknown>;
  returnValueTest: { key?: string; comparator: string; value: string };
}

export interface OperatorCondition {
  operator: "and" | "or";
}

export type AccessCondition = StandardCondition | EvmContractCondition | OperatorCondition;
export type AccessConditionTree = Array<AccessCondition | AccessConditionTree>;

// ------------------------------------------------------------------- builders

/** Hold at least `minAmount` (base units) of $FORGE (or any ERC-20). */
export function forgeTokenGate(opts: {
  tokenAddress: string;
  chain?: Chain;
  minAmount: string | bigint;
}): StandardCondition {
  return {
    contractAddress: opts.tokenAddress,
    standardContractType: "ERC20",
    chain: opts.chain ?? "xdai",
    method: "balanceOf",
    parameters: [":userAddress"],
    returnValueTest: { comparator: ">=", value: opts.minAmount.toString() },
  };
}

/** Own any token of an NFT collection (membership pass). */
export function nftGate(opts: { contractAddress: string; chain?: Chain }): StandardCondition {
  return {
    contractAddress: opts.contractAddress,
    standardContractType: "ERC721",
    chain: opts.chain ?? "xdai",
    method: "balanceOf",
    parameters: [":userAddress"],
    returnValueTest: { comparator: ">", value: "0" },
  };
}

/** Be on a custom allowlist contract: isMember(:userAddress) == true. */
export function allowlistMember(opts: {
  contractAddress: string;
  chain?: Chain;
  functionName?: string;
}): EvmContractCondition {
  const fn = opts.functionName ?? "isMember";
  return {
    contractAddress: opts.contractAddress,
    chain: opts.chain ?? "xdai",
    functionName: fn,
    functionParams: [":userAddress"],
    functionAbi: {
      name: fn, type: "function", stateMutability: "view",
      inputs: [{ name: "account", type: "address" }],
      outputs: [{ name: "", type: "bool" }],
    },
    returnValueTest: { key: "", comparator: "=", value: "true" },
  };
}

/** Have staked at least `minStake` (a custom view returning a uint). */
export function stakedThreshold(opts: {
  contractAddress: string;
  chain?: Chain;
  functionName?: string;
  minStake: string | bigint;
}): EvmContractCondition {
  const fn = opts.functionName ?? "stakeOf";
  return {
    contractAddress: opts.contractAddress,
    chain: opts.chain ?? "xdai",
    functionName: fn,
    functionParams: [":userAddress"],
    functionAbi: {
      name: fn, type: "function", stateMutability: "view",
      inputs: [{ name: "account", type: "address" }],
      outputs: [{ name: "", type: "uint256" }],
    },
    returnValueTest: { key: "", comparator: ">=", value: opts.minStake.toString() },
  };
}

const AND: OperatorCondition = { operator: "and" };
const OR: OperatorCondition = { operator: "or" };

/** Interleave conditions with an "and" operator (Lit's flat-array form). */
export function and(...conds: AccessCondition[]): AccessConditionTree {
  return conds.flatMap((c, i) => (i === 0 ? [c] : [AND, c]));
}
export function or(...conds: AccessCondition[]): AccessConditionTree {
  return conds.flatMap((c, i) => (i === 0 ? [c] : [OR, c]));
}

// ------------------------------------------------------------------- hashing

/** Stable sha256 of the conditions — binds an envelope to its exact gate. */
export async function canonicalConditionsHash(conditions: AccessConditionTree): Promise<string> {
  return sha256Hex(canonicalJson(conditions));
}

// ------------------------------------------------------- local evaluation

export interface ChainState {
  address: string;
  erc20?: Record<string, string | bigint>; // tokenAddress(lowercased) -> balance
  erc721?: Record<string, number>; // collection -> count
  contractBools?: Record<string, boolean>; // `${addr}.${fn}` -> bool
  contractUints?: Record<string, string | bigint>; // `${addr}.${fn}` -> uint
}

function cmpBig(a: bigint, comparator: string, b: bigint): boolean {
  switch (comparator) {
    case ">=": return a >= b;
    case "<=": return a <= b;
    case ">": return a > b;
    case "<": return a < b;
    case "=": return a === b;
    case "!=": return a !== b;
    default: return false;
  }
}

function evalOne(c: AccessCondition, st: ChainState): boolean {
  if ("operator" in c) return true; // handled by the folder
  if ("standardContractType" in c) {
    const addr = c.contractAddress.toLowerCase();
    if (c.standardContractType === "ERC20") {
      const bal = BigInt((st.erc20?.[addr] ?? 0).toString());
      return cmpBig(bal, c.returnValueTest.comparator, BigInt(c.returnValueTest.value));
    }
    if (c.standardContractType === "ERC721") {
      const bal = BigInt(st.erc721?.[addr] ?? 0);
      return cmpBig(bal, c.returnValueTest.comparator, BigInt(c.returnValueTest.value));
    }
    return false;
  }
  // EVM contract condition
  const key = `${c.contractAddress.toLowerCase()}.${c.functionName}`;
  const want = c.returnValueTest.value;
  if (want === "true" || want === "false") {
    const actual = st.contractBools?.[key] ?? false;
    const expected = want === "true";
    return c.returnValueTest.comparator === "!=" ? actual !== expected : actual === expected;
  }
  const actual = BigInt((st.contractUints?.[key] ?? 0).toString());
  return cmpBig(actual, c.returnValueTest.comparator, BigInt(want));
}

/** Simulate Lit node gating: true iff the state satisfies the conditions. */
export function evaluate(tree: AccessConditionTree, st: ChainState): boolean {
  let acc: boolean | null = null;
  let op: "and" | "or" = "and";
  for (const node of tree) {
    if (Array.isArray(node)) {
      acc = combine(acc, op, evaluate(node, st));
    } else if ("operator" in node) {
      op = node.operator;
    } else {
      acc = combine(acc, op, evalOne(node, st));
    }
  }
  return acc ?? false;
}

function combine(acc: boolean | null, op: "and" | "or", v: boolean): boolean {
  if (acc === null) return v;
  return op === "and" ? acc && v : acc || v;
}
