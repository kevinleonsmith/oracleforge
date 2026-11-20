// Deployment address book. Defaults come from deployments/<network>.json (written
// by the deploy script); any NEXT_PUBLIC_* env var overrides.
import chiado from "@/deployments/chiado.json";

type Hex = `0x${string}`;

export interface Deployment {
  chainId: number;
  contracts: {
    MarketEngine: Hex;
    Treasury: Hex;
    ChainlinkOracleAdapter: Hex;
    ForgeToken: Hex;
  };
  collateral: Hex;
  collateralDecimals: number;
  tables: Record<string, string>;
}

const BOOKS: Record<number, Deployment> = {
  10200: chiado as unknown as Deployment,
};

const env = (k: string) => process.env[k];

export function getDeployment(chainId = 10200): Deployment {
  const base = BOOKS[chainId] ?? BOOKS[10200];
  // env overrides (useful before deployments/*.json is committed)
  return {
    ...base,
    contracts: {
      ...base.contracts,
      MarketEngine: (env("NEXT_PUBLIC_MARKET_ENGINE") as Hex) ?? base.contracts.MarketEngine,
      ChainlinkOracleAdapter:
        (env("NEXT_PUBLIC_ORACLE_ADAPTER") as Hex) ?? base.contracts.ChainlinkOracleAdapter,
    },
    collateral: (env("NEXT_PUBLIC_COLLATERAL") as Hex) ?? base.collateral,
    tables: {
      ...base.tables,
      markets: env("NEXT_PUBLIC_MARKETS_TABLE") ?? base.tables.markets,
    },
  };
}

const ZERO = "0x0000000000000000000000000000000000000000";
export function isDeployed(d: Deployment): boolean {
  return d.contracts.MarketEngine !== ZERO;
}
