// Lit client: encrypt data under access-control conditions, decrypt if the caller
// satisfies them.
//
// - MockLitClient  : real AES-GCM, gated by a simulated chain state. Faithful to
//                    Lit's model (the symmetric key is a function of the conditions,
//                    "released" only when they pass) and fully testable offline.
// - RealLitClient  : wraps the @lit-protocol SDK (threshold BLS across the Lit
//                    network). Lazy-imported; the live path.
import {
  type AccessConditionTree,
  type Chain,
  type ChainState,
  canonicalConditionsHash,
  evaluate,
} from "./conditions.ts";
import { aesDecrypt, aesEncrypt, deriveKey, fromBase64, sha256Hex, toBase64 } from "./crypto.ts";
import type { EncryptedEnvelope } from "./envelope.ts";

export class AccessDeniedError extends Error {}
export class IntegrityError extends Error {}

export interface AuthContext {
  address: string;
  state?: ChainState; // mock gating
  sessionSigs?: unknown; // real Lit gating
}

export interface LitClient {
  encrypt(
    plaintext: string,
    conditions: AccessConditionTree,
    chain: Chain,
    meta?: Record<string, unknown>
  ): Promise<EncryptedEnvelope>;
  decrypt(env: EncryptedEnvelope, auth: AuthContext): Promise<string>;
}

export class MockLitClient implements LitClient {
  private secret: string;

  constructor(networkSecret = "oracleforge-lit-mock-network") {
    this.secret = networkSecret;
  }

  async encrypt(
    plaintext: string,
    conditions: AccessConditionTree,
    chain: Chain,
    meta: Record<string, unknown> = {}
  ): Promise<EncryptedEnvelope> {
    const conditionsHash = await canonicalConditionsHash(conditions);
    const key = await deriveKey(this.secret, conditionsHash); // key is a function of the gate
    const packed = await aesEncrypt(key, plaintext);
    return {
      version: "mock-1",
      ciphertext: toBase64(packed),
      dataToEncryptHash: await sha256Hex(plaintext),
      conditionsHash,
      accessControlConditions: conditions,
      chain,
      meta,
    };
  }

  async decrypt(env: EncryptedEnvelope, auth: AuthContext): Promise<string> {
    // 1) tamper check: the conditions must match the hash sealed at encrypt time,
    //    so an attacker can't weaken the gate to get the key.
    const recomputed = await canonicalConditionsHash(env.accessControlConditions);
    if (recomputed !== env.conditionsHash) throw new IntegrityError("conditions do not match sealed hash");

    // 2) gating: evaluate the ACCs against the caller's chain state.
    if (!auth.state || !evaluate(env.accessControlConditions, auth.state)) {
      throw new AccessDeniedError("access control conditions not satisfied");
    }

    // 3) decrypt and verify plaintext integrity.
    const key = await deriveKey(this.secret, env.conditionsHash);
    const plaintext = await aesDecrypt(key, fromBase64(env.ciphertext));
    if ((await sha256Hex(plaintext)) !== env.dataToEncryptHash) {
      throw new IntegrityError("plaintext hash mismatch");
    }
    return plaintext;
  }
}

/** Live client backed by the Lit network. Needs @lit-protocol/* and a wallet. */
export class RealLitClient implements LitClient {
  private network: string;
  private client: unknown = null;

  constructor(network = "datil-dev") {
    this.network = network;
  }

  private async connect(): Promise<any> {
    // istanbul ignore next — requires the Lit SDK + network
    if (!this.client) {
      const { LitNodeClient } = await import("@lit-protocol/lit-node-client");
      const c = new LitNodeClient({ litNetwork: this.network });
      await c.connect();
      this.client = c;
    }
    return this.client;
  }

  async encrypt(
    plaintext: string,
    conditions: AccessConditionTree,
    chain: Chain,
    meta: Record<string, unknown> = {}
  ): Promise<EncryptedEnvelope> {
    // istanbul ignore next
    const client = await this.connect();
    const { encryptString } = await import("@lit-protocol/encryption");
    const { ciphertext, dataToEncryptHash } = await encryptString(
      { accessControlConditions: conditions as any, dataToEncrypt: plaintext },
      client as any
    );
    return {
      version: "lit-1",
      ciphertext,
      dataToEncryptHash,
      conditionsHash: await canonicalConditionsHash(conditions),
      accessControlConditions: conditions,
      chain,
      meta,
    };
  }

  async decrypt(env: EncryptedEnvelope, auth: AuthContext): Promise<string> {
    // istanbul ignore next
    const client = await this.connect();
    const { decryptToString } = await import("@lit-protocol/encryption");
    return decryptToString(
      {
        accessControlConditions: env.accessControlConditions as any,
        ciphertext: env.ciphertext,
        dataToEncryptHash: env.dataToEncryptHash,
        chain: env.chain,
        sessionSigs: auth.sessionSigs as any,
      },
      client as any
    );
  }
}
