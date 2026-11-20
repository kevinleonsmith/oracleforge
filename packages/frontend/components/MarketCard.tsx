import type { Market } from "@oracleforge/shared/types";

const CAT_COLOR: Record<string, string> = {
  MACRO: "var(--cyan)", CRYPTO: "var(--ember)", GEO: "var(--violet)", CLIMATE: "var(--green)",
};

function usd(decimalStr: string) {
  const n = Number(decimalStr);
  return n >= 1_000_000 ? `$${(n / 1_000_000).toFixed(1)}M` : `$${(n / 1000).toFixed(0)}K`;
}

export function MarketCard({ m }: { m: Market }) {
  const yes = Math.round(m.aiProbBps / 100);
  const tvl = usd((Number(m.yesPool) + Number(m.noPool)).toString());
  return (
    <div style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 10, padding: 13 }}>
      <span style={{
        fontFamily: "var(--mono)", fontSize: 10, letterSpacing: ".1em",
        padding: "2px 7px", borderRadius: 5, color: CAT_COLOR[m.category],
        background: "color-mix(in srgb, " + CAT_COLOR[m.category] + " 12%, transparent)",
      }}>{m.category}</span>
      <div style={{ fontSize: 13, margin: "9px 0 10px", minHeight: 34, lineHeight: 1.32 }}>{m.question}</div>
      <div style={{ display: "flex", gap: 7 }}>
        <div style={{ flex: 1, textAlign: "center", border: "1px solid var(--line)", borderRadius: 7, padding: "7px 0", background: "var(--panel-2)" }}>
          <div className="mono" style={{ fontSize: 10, color: "var(--faint)" }}>YES</div>
          <div style={{ fontFamily: "var(--display)", fontWeight: 600, fontSize: 16, color: "var(--green)" }}>{yes}%</div>
        </div>
        <div style={{ flex: 1, textAlign: "center", border: "1px solid var(--line)", borderRadius: 7, padding: "7px 0", background: "var(--panel-2)" }}>
          <div className="mono" style={{ fontSize: 10, color: "var(--faint)" }}>NO</div>
          <div style={{ fontFamily: "var(--display)", fontWeight: 600, fontSize: 16, color: "var(--red)" }}>{100 - yes}%</div>
        </div>
      </div>
      <div className="mono" style={{ fontSize: 10, color: "var(--faint)", marginTop: 9 }}>{tvl} TVL · AI prob {yes}%</div>
    </div>
  );
}
