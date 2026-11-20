// viem bindings for the OracleForge contracts. ABIs are the minimal fragments
// the frontend needs; generate full ABIs with `forge build` and import from
// packages/contracts/out when wiring real writes.
import { createPublicClient, http, type Address } from "viem";
import { gnosis, gnosisChiado } from "viem/chains";
import type { AddressBook } from "@oracleforge/shared/types";

export const CHAIN = process.env.NEXT_PUBLIC_CHAIN === "gnosis" ? gnosis : gnosisChiado;

export const publicClient = createPublicClient({
  chain: CHAIN,
  transport: http(process.env.NEXT_PUBLIC_RPC_URL),
});

// Populated from packages/contracts deploy output (broadcast/*.json).
export const addresses: Partial<AddressBook> = {
  chainId: CHAIN.id,
};

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
        { name: "status", type: "uint8" },
        { name: "outcome", type: "uint8" },
        { name: "yesPool", type: "uint256" },
        { name: "noPool", type: "uint256" },
      ],
    }],
  },
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
] as const;

export async function readMarket(marketId: `0x${string}`, engine: Address) {
  return publicClient.readContract({
    address: engine, abi: marketEngineAbi, functionName: "getMarket", args: [marketId],
  });
}
