// The portable encrypted record. It is plain JSON, so it archives to Arweave
// permanently (encrypted at rest) and indexes in Tableland — only gated holders
// can ever decrypt it.
import type { AccessConditionTree, Chain } from "./conditions.ts";

export interface EncryptedEnvelope {
  version: string;
  ciphertext: string; // base64(iv || AES-GCM ciphertext), or the Lit ciphertext
  dataToEncryptHash: string; // sha256 of the plaintext (integrity)
  conditionsHash: string; // sha256 of the canonical conditions (tamper-evidence)
  accessControlConditions: AccessConditionTree;
  chain: Chain;
  meta: Record<string, unknown>; // e.g. { kind: "alpha", marketId, createdAt }
}

export function serializeEnvelope(env: EncryptedEnvelope): string {
  return JSON.stringify(env);
}

export function deserializeEnvelope(s: string): EncryptedEnvelope {
  const o = JSON.parse(s) as EncryptedEnvelope;
  for (const k of ["ciphertext", "dataToEncryptHash", "conditionsHash", "accessControlConditions"]) {
    if (!(k in o)) throw new Error(`envelope missing ${k}`);
  }
  return o;
}
