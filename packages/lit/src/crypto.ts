// Portable crypto helpers (WebCrypto) — run in Node and the browser.
// Used by the mock Lit backend and for canonical condition hashing.

const subtle: SubtleCrypto = globalThis.crypto.subtle;
const te = new TextEncoder();
const td = new TextDecoder();

/** Deterministic JSON (sorted keys) so a hash is stable across key order. */
export function canonicalJson(v: unknown): string {
  if (v === null || typeof v !== "object") return JSON.stringify(v);
  if (Array.isArray(v)) return "[" + v.map(canonicalJson).join(",") + "]";
  const o = v as Record<string, unknown>;
  return (
    "{" +
    Object.keys(o)
      .sort()
      .map((k) => JSON.stringify(k) + ":" + canonicalJson(o[k]))
      .join(",") +
    "}"
  );
}

export async function sha256Hex(data: string): Promise<string> {
  const d = await subtle.digest("SHA-256", te.encode(data));
  return "0x" + [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function toBase64(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return typeof btoa !== "undefined" ? btoa(s) : Buffer.from(bytes).toString("base64");
}

export function fromBase64(s: string): Uint8Array {
  const bin = typeof atob !== "undefined" ? atob(s) : Buffer.from(s, "base64").toString("binary");
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** HKDF-derive an AES-GCM key from a secret + public salt (the conditions hash). */
export async function deriveKey(secret: string, salt: string): Promise<CryptoKey> {
  const base = await subtle.importKey("raw", te.encode(secret), "HKDF", false, ["deriveKey"]);
  return subtle.deriveKey(
    { name: "HKDF", hash: "SHA-256", salt: te.encode(salt), info: new Uint8Array() },
    base,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"]
  );
}

export async function aesEncrypt(key: CryptoKey, plaintext: string): Promise<Uint8Array> {
  const iv = globalThis.crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(await subtle.encrypt({ name: "AES-GCM", iv }, key, te.encode(plaintext)));
  const packed = new Uint8Array(iv.length + ct.length);
  packed.set(iv);
  packed.set(ct, iv.length);
  return packed; // iv (12) || ciphertext
}

export async function aesDecrypt(key: CryptoKey, packed: Uint8Array): Promise<string> {
  const iv = packed.slice(0, 12);
  const ct = packed.slice(12);
  const pt = await subtle.decrypt({ name: "AES-GCM", iv }, key, ct);
  return td.decode(pt);
}
