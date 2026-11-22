// Data facade. Selects the live on-chain/Tableland client or the mock set via
// NEXT_PUBLIC_DATA_SOURCE ("chain" | "mock"). The page imports only from here, so
// swapping sources needs no page changes.
//
//   NEXT_PUBLIC_DATA_SOURCE=chain   # read deployed Chiado contracts + Tableland
//   NEXT_PUBLIC_DATA_SOURCE=mock    # design-time sample data (default)
import * as mock from "./mockApi";
import * as chain from "./chainApi";

const useChain = process.env.NEXT_PUBLIC_DATA_SOURCE === "chain";
const impl = useChain ? chain : mock;

export const DATA_SOURCE: "chain" | "mock" = useChain ? "chain" : "mock";

export const getOpenMarkets = impl.getOpenMarkets;
export const getPrediction = impl.getPrediction;
export const getActiveProposals = impl.getActiveProposals;
export const getProtocolStats = impl.getProtocolStats;
export const getScalarMarkets = impl.getScalarMarkets;
export const getCategoricalMarkets = impl.getCategoricalMarkets;
export const getPositions = impl.getPositions;
