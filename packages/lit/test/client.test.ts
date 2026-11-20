// Run with: node --test --experimental-strip-types test/client.test.ts
import test from "node:test";
import assert from "node:assert/strict";

import { forgeTokenGate, or, allowlistMember, type ChainState } from "../src/conditions.ts";
import { serializeEnvelope, deserializeEnvelope } from "../src/envelope.ts";
import { MockLitClient, AccessDeniedError, IntegrityError } from "../src/litClient.ts";

const FORGE = "0xForge000000000000000000000000000000Beef";
const ALLOW = "0xAllow00000000000000000000000000000000CAFE";
const ALPHA = "ALPHA: CPI model puts YES at 0.81 with 92% confidence.";

const gate = [forgeTokenGate({ tokenAddress: FORGE, minAmount: "1000000000000000000" })]; // 1 FORGE
const holder: ChainState = { address: "0xA", erc20: { [FORGE.toLowerCase()]: "5000000000000000000" } };
const nonHolder: ChainState = { address: "0xB", erc20: { [FORGE.toLowerCase()]: "0" } };

test("holder can round-trip encrypt -> decrypt", async () => {
  const lit = new MockLitClient();
  const env = await lit.encrypt(ALPHA, gate, "xdai", { kind: "alpha", marketId: "0xa7f3" });
  assert.equal(env.version, "mock-1");
  assert.match(env.conditionsHash, /^0x/);
  const out = await lit.decrypt(env, { address: "0xA", state: holder });
  assert.equal(out, ALPHA);
});

test("non-holder is denied", async () => {
  const lit = new MockLitClient();
  const env = await lit.encrypt(ALPHA, gate, "xdai");
  await assert.rejects(lit.decrypt(env, { address: "0xB", state: nonHolder }), AccessDeniedError);
});

test("missing auth state is denied", async () => {
  const lit = new MockLitClient();
  const env = await lit.encrypt(ALPHA, gate, "xdai");
  await assert.rejects(lit.decrypt(env, { address: "0xB" }), AccessDeniedError);
});

test("tampering with the conditions is detected (can't weaken the gate)", async () => {
  const lit = new MockLitClient();
  const env = await lit.encrypt(ALPHA, gate, "xdai");
  // attacker swaps in a trivially-true gate but keeps the sealed hash
  const forged = { ...env, accessControlConditions: [allowlistMember({ contractAddress: ALLOW })] };
  await assert.rejects(lit.decrypt(forged, { address: "0xB", state: nonHolder }), IntegrityError);
});

test("OR gate: either qualifying path decrypts", async () => {
  const lit = new MockLitClient();
  const g = or(
    forgeTokenGate({ tokenAddress: FORGE, minAmount: "1000000000000000000" }),
    allowlistMember({ contractAddress: ALLOW })
  );
  const env = await lit.encrypt(ALPHA, g, "xdai");
  const key = `${ALLOW.toLowerCase()}.isMember`;
  const allowlisted: ChainState = { address: "0xC", contractBools: { [key]: true } };
  assert.equal(await lit.decrypt(env, { address: "0xC", state: allowlisted }), ALPHA);
});

test("envelope serialize/deserialize round-trips", async () => {
  const lit = new MockLitClient();
  const env = await lit.encrypt(ALPHA, gate, "xdai", { kind: "alpha" });
  const back = deserializeEnvelope(serializeEnvelope(env));
  assert.deepEqual(back.accessControlConditions, env.accessControlConditions);
  assert.equal(back.ciphertext, env.ciphertext);
  // and it still decrypts for a holder
  assert.equal(await lit.decrypt(back, { address: "0xA", state: holder }), ALPHA);
});

test("deserialize rejects a malformed envelope", () => {
  assert.throws(() => deserializeEnvelope('{"ciphertext":"x"}'), /missing/);
});
