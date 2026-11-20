// OracleForge Lit integration — token-gated / encrypted private markets.
//
// Encrypt alpha reports, private market details, or institutional intelligence
// under on-chain access conditions ("holds >= N $FORGE", "on the allowlist",
// "staked >= X"); only wallets that satisfy them can decrypt. The envelope is
// plain JSON, so it archives permanently to Arweave (encrypted at rest) and
// indexes in Tableland.
export * from "./conditions.ts";
export * from "./envelope.ts";
export * from "./litClient.ts";
export const VERSION = "0.1.0";
