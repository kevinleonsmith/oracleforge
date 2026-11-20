#!/usr/bin/env node
// Extract deployed addresses from a Foundry broadcast into deployments/<network>.json.
//
//   node scripts/extract-addresses.mjs \
//     ../contracts/broadcast/Deploy.s.sol/10200/run-latest.json \
//     deployments/chiado.json --network chiado --collateral 0x...
//
// The pure `extractAddresses` is unit-tested; the CLI part just does file I/O.
import { readFileSync, writeFileSync } from "node:fs";

const WANTED = ["MarketEngine", "Treasury", "ChainlinkOracleAdapter", "ForgeToken"];

/** Build a deployment book from a parsed Foundry broadcast object. */
export function extractAddresses(broadcast, opts = {}) {
  const contracts = Object.fromEntries(WANTED.map((n) => [n, ZERO]));
  for (const tx of broadcast.transactions ?? []) {
    if (tx.transactionType === "CREATE" && WANTED.includes(tx.contractName)) {
      contracts[tx.contractName] = (tx.contractAddress ?? ZERO).toLowerCase();
    }
  }
  return {
    chainId: opts.chainId ?? broadcast.chain ?? 10200,
    network: opts.network ?? "chiado",
    contracts,
    collateral: (opts.collateral ?? "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d").toLowerCase(),
    collateralDecimals: opts.collateralDecimals ?? 18,
    tables: opts.tables ?? {
      markets: "markets", predictions: "predictions",
      confidence_scores: "confidence_scores", governance_proposals: "governance_proposals",
    },
  };
}

const ZERO = "0x0000000000000000000000000000000000000000";

function parseArgs(argv) {
  const [broadcastPath, outPath, ...rest] = argv;
  const opts = {};
  for (let i = 0; i < rest.length; i += 2) {
    const key = rest[i].replace(/^--/, "");
    opts[key] = rest[i + 1];
  }
  return { broadcastPath, outPath, opts };
}

// run only when invoked directly (not when imported by a test)
if (import.meta.url === `file://${process.argv[1]}`) {
  const { broadcastPath, outPath, opts } = parseArgs(process.argv.slice(2));
  if (!broadcastPath || !outPath) {
    console.error("usage: extract-addresses.mjs <broadcast.json> <out.json> [--network x --collateral 0x..]");
    process.exit(1);
  }
  const broadcast = JSON.parse(readFileSync(broadcastPath, "utf8"));
  const book = extractAddresses(broadcast, opts);
  writeFileSync(outPath, JSON.stringify(book, null, 2) + "\n");
  console.log(`wrote ${outPath}:`);
  for (const [k, v] of Object.entries(book.contracts)) console.log(`  ${k.padEnd(24)} ${v}`);
}
