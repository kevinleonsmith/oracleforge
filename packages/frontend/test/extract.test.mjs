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
    { transactionType: "CALL", contractName: "ChainlinkOracleAdapter", contractAddress: "0xCCc0000000000000000000000000000000000003" },
  ],
};

test("extracts all four contract addresses, lowercased", () => {
  const book = extractAddresses(BROADCAST, { network: "chiado" });
  assert.equal(book.chainId, 10200);
  assert.equal(book.contracts.MarketEngine, "0xddd0000000000000000000000000000000000004");
  assert.equal(book.contracts.Treasury, "0xaaa0000000000000000000000000000000000001");
  assert.equal(book.contracts.ForgeToken, "0xbbb0000000000000000000000000000000000002");
  assert.equal(book.contracts.ChainlinkOracleAdapter, "0xccc0000000000000000000000000000000000003");
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
