// Read-only Tableland access via the gateway's HTTP query endpoint. No SDK needed
// for reads, so this works directly in server components.
import type { Row } from "./queries";

const GATEWAY = (
  process.env.NEXT_PUBLIC_TABLELAND_GATEWAY ?? "https://tableland.network"
).replace(/\/$/, "");

/** Run a read-only SQL statement; returns rows as objects (empty on failure). */
export async function queryTableland(sql: string): Promise<Row[]> {
  const url = `${GATEWAY}/api/v1/query?statement=${encodeURIComponent(sql)}&format=objects`;
  try {
    const res = await fetch(url, { next: { revalidate: 15 } });
    if (!res.ok) return [];
    return (await res.json()) as Row[];
  } catch {
    return []; // gateway unreachable -> render an empty state rather than crash
  }
}
