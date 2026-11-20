// Runnable demo: encrypt an alpha report behind a $FORGE token gate, then show a
// holder decrypting and a non-holder being denied.
//   node --experimental-strip-types scripts/demo.ts
import { forgeTokenGate, type ChainState } from "../src/conditions.ts";
import { MockLitClient, AccessDeniedError } from "../src/litClient.ts";

const FORGE = "0xForge000000000000000000000000000000Beef";
const ALPHA = "ALPHA — forecast model puts YES on MKT-0xA7F3 at 0.81 (92% conf).";

async function main(): Promise<void> {
  const lit = new MockLitClient();
  const gate = [forgeTokenGate({ tokenAddress: FORGE, minAmount: "1000000000000000000" })]; // >= 1 FORGE

  const env = await lit.encrypt(ALPHA, gate, "xdai", { kind: "alpha", marketId: "0xA7F3" });
  console.log("encrypted envelope:");
  console.log(`  ciphertext:        ${env.ciphertext.slice(0, 32)}…`);
  console.log(`  dataToEncryptHash: ${env.dataToEncryptHash}`);
  console.log(`  conditionsHash:    ${env.conditionsHash}`);
  console.log(`  gate:              holds >= 1 $FORGE on xdai\n`);

  const holder: ChainState = { address: "0xHodler", erc20: { [FORGE.toLowerCase()]: "5000000000000000000" } };
  const nonHolder: ChainState = { address: "0xNobody", erc20: { [FORGE.toLowerCase()]: "0" } };

  console.log("holder (5 FORGE)   ->", await lit.decrypt(env, { address: "0xHodler", state: holder }));
  try {
    await lit.decrypt(env, { address: "0xNobody", state: nonHolder });
  } catch (e) {
    console.log("non-holder (0)     ->", e instanceof AccessDeniedError ? "ACCESS DENIED ✓" : `error: ${e}`);
  }
}

main();
