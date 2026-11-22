// Run with: node --test test/extract.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { extractAddresses } from "../scripts/extract-addresses.mjs";

const BROADCAST = {
  chain: 10200,
  transactions: [
    { transactionType: "CREATE", contractName: "Treasury", contractAddress: "0xAAa0000000000000000000000000000000000001" },
    { transactionType: "CREATE", contractName: "ForgeToken", contractAddress: "0xBBb0000000000000000000000000000000000002" },
    { transactionType: "CREATE", contractName: "ChainlinkOracleAdapter", contractAddress: "0xCCc0000000000000000000000000000000000003" },
    { transactionType: "CREATE", contractName: "MarketEngine", contractAddress: "0xDDd0000000000000000000000000000000000004" },
    { transactionType: "CREATE", contractName: "ScalarChainlinkAdapter", contractAddress: "0xEEe0000000000000000000000000000000000005" },
    { transactionType: "CREATE", contractName: "ScalarMarketEngine", contractAddress: "0xFFf0000000000000000000000000000000000006" },
    { transactionType: "CREATE", contractName: "CategoricalChainlinkAdapter", contractAddress: "0x1110000000000000000000000000000000000007" },
    { transactionType: "CREATE", contractName: "CategoricalMarketEngine", contractAddress: "0x2220000000000000000000000000000000000008" },
    { transactionType: "CREATE", contractName: "ForgeGovernor", contractAddress: "0x3330000000000000000000000000000000000009" },
    { transactionType: "CALL", contractName: "ChainlinkOracleAdapter", contractAddress: "0xCCc0000000000000000000000000000000000003" },
  ],
};

test("extracts the binary contract addresses, lowercased", () => {
  const book = extractAddresses(BROADCAST, { network: "chiado" });
  assert.equal(book.chainId, 10200);
  assert.equal(book.contracts.MarketEngine, "0xddd0000000000000000000000000000000000004");
  assert.equal(book.contracts.Treasury, "0xaaa0000000000000000000000000000000000001");
  assert.equal(book.contracts.ForgeToken, "0xbbb0000000000000000000000000000000000002");
  assert.equal(book.contracts.ChainlinkOracleAdapter, "0xccc0000000000000000000000000000000000003");
});

test("extracts the scalar + categorical engines and their adapters", () => {
  const book = extractAddresses(BROADCAST, { network: "chiado" });
  assert.equal(book.contracts.ScalarChainlinkAdapter, "0xeee0000000000000000000000000000000000005");
  assert.equal(book.contracts.ScalarMarketEngine, "0xfff0000000000000000000000000000000000006");
  assert.equal(book.contracts.CategoricalChainlinkAdapter, "0x1110000000000000000000000000000000000007");
  assert.equal(book.contracts.CategoricalMarketEngine, "0x2220000000000000000000000000000000000008");
});

test("extracts the ForgeGovernor address", () => {
  const book = extractAddresses(BROADCAST, { network: "chiado" });
  assert.equal(book.contracts.ForgeGovernor, "0x3330000000000000000000000000000000000009");
});

test("uses a self-deployed MockERC20 as the collateral (testnet/demo)", () => {
  const demo = {
    transactions: [
      { transactionType: "CREATE", contractName: "MockERC20", contractAddress: "0xCAFe000000000000000000000000000000000001" },
      { transactionType: "CREATE", contractName: "MarketEngine", contractAddress: "0xDDd0000000000000000000000000000000000004" },
    ],
  };
  // no --collateral opt -> the deployed demo token is the collateral
  assert.equal(extractAddresses(demo).collateral, "0xcafe000000000000000000000000000000000001");
  // an explicit --collateral still wins (production: real WXDAI)
  assert.equal(
    extractAddresses(demo, { collateral: "0xBEEF000000000000000000000000000000000002" }).collateral,
    "0xbeef000000000000000000000000000000000002",
  );
});

test("falls back to WXDAI when there is no demo token and no opt", () => {
  const book = extractAddresses(BROADCAST); // BROADCAST has no MockERC20
  assert.equal(book.collateral, "0xe91d153e0b41518a2ce8dd3d7944fa863463a97d");
});

test("missing contracts stay zero; CALLs ignored", () => {
  const book = extractAddresses({ transactions: [
    { transactionType: "CREATE", contractName: "MarketEngine", contractAddress: "0x1234000000000000000000000000000000000000" },
  ] }, { chainId: 10200 });
  assert.equal(book.contracts.MarketEngine, "0x1234000000000000000000000000000000000000");
  assert.equal(book.contracts.Treasury, "0x0000000000000000000000000000000000000000");
});

test("defaults: collateral + tables present", () => {
  const book = extractAddresses(BROADCAST);
  assert.equal(book.collateralDecimals, 18);
  assert.equal(book.tables.markets, "markets");
  assert.match(book.collateral, /^0x[0-9a-f]{40}$/);
});
