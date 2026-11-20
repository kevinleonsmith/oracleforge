// Run with: node --test --experimental-strip-types test/conditions.test.ts
import test from "node:test";
import assert from "node:assert/strict";

import {
  forgeTokenGate, nftGate, allowlistMember, stakedThreshold,
  and, or, evaluate, canonicalConditionsHash,
  type ChainState,
} from "../src/conditions.ts";

const FORGE = "0xForge000000000000000000000000000000Beef";
const ALLOW = "0xAllow00000000000000000000000000000000CAFE";

test("forgeTokenGate builds a Lit ERC20 balance condition", () => {
  const c = forgeTokenGate({ tokenAddress: FORGE, minAmount: 1000n });
  assert.equal(c.standardContractType, "ERC20");
  assert.equal(c.method, "balanceOf");
  assert.deepEqual(c.parameters, [":userAddress"]);
  assert.equal(c.returnValueTest.comparator, ">=");
  assert.equal(c.returnValueTest.value, "1000");
  assert.equal(c.chain, "xdai");
});

test("evaluate: holder passes the token gate, non-holder fails", () => {
  const gate = [forgeTokenGate({ tokenAddress: FORGE, minAmount: "1000" })];
  const holder: ChainState = { address: "0xA", erc20: { [FORGE.toLowerCase()]: "1500" } };
  const poor: ChainState = { address: "0xB", erc20: { [FORGE.toLowerCase()]: "999" } };
  const none: ChainState = { address: "0xC" };
  assert.equal(evaluate(gate, holder), true);
  assert.equal(evaluate(gate, poor), false);
  assert.equal(evaluate(gate, none), false);
});

test("evaluate: allowlist boolean condition", () => {
  const gate = [allowlistMember({ contractAddress: ALLOW })];
  const key = `${ALLOW.toLowerCase()}.isMember`;
  assert.equal(evaluate(gate, { address: "0xA", contractBools: { [key]: true } }), true);
  assert.equal(evaluate(gate, { address: "0xB", contractBools: { [key]: false } }), false);
  assert.equal(evaluate(gate, { address: "0xC" }), false);
});

test("evaluate: OR passes if either holds; AND needs both", () => {
  const key = `${ALLOW.toLowerCase()}.isMember`;
  const orGate = or(forgeTokenGate({ tokenAddress: FORGE, minAmount: "1000" }), allowlistMember({ contractAddress: ALLOW }));
  const andGate = and(forgeTokenGate({ tokenAddress: FORGE, minAmount: "1000" }), allowlistMember({ contractAddress: ALLOW }));

  const onlyAllow: ChainState = { address: "0xA", contractBools: { [key]: true } };
  const both: ChainState = { address: "0xB", erc20: { [FORGE.toLowerCase()]: "2000" }, contractBools: { [key]: true } };

  assert.equal(evaluate(orGate, onlyAllow), true);
  assert.equal(evaluate(andGate, onlyAllow), false);
  assert.equal(evaluate(andGate, both), true);
});

test("evaluate: staked uint threshold", () => {
  const gate = [stakedThreshold({ contractAddress: ALLOW, minStake: "500" })];
  const key = `${ALLOW.toLowerCase()}.stakeOf`;
  assert.equal(evaluate(gate, { address: "0xA", contractUints: { [key]: "500" } }), true);
  assert.equal(evaluate(gate, { address: "0xB", contractUints: { [key]: "499" } }), false);
});

test("nftGate requires balance > 0", () => {
  const gate = [nftGate({ contractAddress: ALLOW })];
  assert.equal(evaluate(gate, { address: "0xA", erc721: { [ALLOW.toLowerCase()]: 1 } }), true);
  assert.equal(evaluate(gate, { address: "0xB", erc721: { [ALLOW.toLowerCase()]: 0 } }), false);
});

test("canonicalConditionsHash is order-invariant and stable", async () => {
  const g = forgeTokenGate({ tokenAddress: FORGE, minAmount: "1000" });
  const h1 = await canonicalConditionsHash([g]);
  const h2 = await canonicalConditionsHash([{ ...g }]);
  assert.equal(h1, h2);
  assert.match(h1, /^0x[0-9a-f]{64}$/);
});
