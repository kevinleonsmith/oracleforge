"use client";
import { useMemo, useState, type CSSProperties } from "react";
import type { Market } from "@oracleforge/shared/types";
import { formatCompact } from "@/lib/format";
import { catColor, toUiMarket, type Position, type UiMarket } from "@/lib/ui";
import { ProbabilityChart } from "./ProbabilityChart";
import { TradeDrawer } from "./TradeDrawer";

const money = (n: number) => (n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${n.toFixed(0)}`);
const impliedYes = (m: UiMarket) => Math.round((m.yes / (m.yes + m.no || 1)) * 100);

// Deterministic illustrative probability history (no RNG -> no hydration mismatch).
function demoSeries(): { ai: number[]; market: number[] } {
  const ai: number[] = [];
  const market: number[] = [];
  for (let i = 0; i < 48; i++) {
    const t = i / 47;
    const v = 0.41 + (0.67 - 0.41) * t + 0.04 * Math.sin(i * 0.7);
    ai.push(Math.max(0.2, Math.min(0.82, v)));
    market.push(Math.max(0.15, Math.min(0.85, v + 0.03 * Math.sin(i * 0.9 + 1))));
  }
  return { ai, market };
}

const CONFIDENCE: Array<[string, number, string]> = [
  ["Macro / rates", 81, "var(--cyan)"],
  ["News NLP", 76, "var(--violet)"],
  ["On-chain flow", 71, "var(--teal)"],
  ["Sentiment", 63, "var(--ember)"],
  ["Historical base", 88, "var(--green)"],
];

export function MarketsView({ initialMarkets }: { initialMarkets: Market[] }) {
  const [markets, setMarkets] = useState<UiMarket[]>(() => initialMarkets.map(toUiMarket));
  const [positions, setPositions] = useState<Position[]>([]);
  const [selected, setSelected] = useState<UiMarket | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const series = useMemo(demoSeries, []);
  const confAvg = Math.round(CONFIDENCE.reduce((a, c) => a + c[1], 0) / CONFIDENCE.length);

  function placePosition(p: Position) {
    setMarkets((ms) =>
      ms.map((m) =>
        m.id === p.id ? { ...m, [p.side === "YES" ? "yes" : "no"]: (p.side === "YES" ? m.yes : m.no) + p.stake } : m
      )
    );
    setPositions((ps) => [p, ...ps]);
    setSelected(null);
    setToast(`Position placed · ${p.side} ${money(p.stake)} on ${p.id}`);
    window.setTimeout(() => setToast(null), 2600);
  }

  return (
    <>
      {/* AI prediction engine */}
      <div className="sec">
        <div className="sec-head">
          <div>
            <div className="eyebrow">Core Module 01</div>
            <h2>AI Prediction Engine</h2>
            <p>Probability is initialized by a deterministic Cartesi forecast and recomputed each block. Click any market to open a position.</p>
          </div>
          <div className="legend-live"><span className="dot live" /> streaming · 12s</div>
        </div>
        <div className="grid">
          <div className="panel span7">
            <div className="p-head"><div className="ico">◈</div><h3>Probability History</h3><span className="tag">Cartesi · deterministic</span></div>
            <div className="engine-top">
              <div>
                <div className="q">Will US CPI print below 2.6% YoY for December 2026?</div>
                <div className="meta">MKT-0xA7F3 · opened 14d ago · settles via Chainlink ECON feed</div>
              </div>
              <div className="prob-big"><div className="pv">67%</div><div className="pl">YES PROBABILITY</div></div>
            </div>
            <ProbabilityChart data={series.ai} marketLine={series.market} />
            <div className="chart-foot">
              <span><span className="sw" style={{ background: "var(--cyan)" }} />AI probability</span>
              <span><span className="sw" style={{ background: "var(--violet)", opacity: 0.6 }} />Market-implied</span>
              <span style={{ marginLeft: "auto" }}>Monte Carlo n=50,000 · σ shaded</span>
            </div>
          </div>
          <div className="panel span5">
            <div className="p-head"><div className="ico">◎</div><h3>Confidence Decomposition</h3><span className="tag">per-source</span></div>
            <div className="conf-row">
              <div className="ring" style={{ "--p": confAvg } as CSSProperties}><span className="rv">{confAvg}%</span></div>
              <div className="conf-list">
                {CONFIDENCE.map(([n, v, c]) => (
                  <div className="conf-item" key={n}>
                    <span className="cl">{n}</span>
                    <div className="bar"><i style={{ width: `${v}%`, background: c }} /></div>
                    <span className="cv">{v}%</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Market explorer */}
      <div className="sec">
        <div className="sec-head">
          <div>
            <div className="eyebrow">Market Explorer</div>
            <h2>Live Markets</h2>
            <p>Click a market to trade. YES/NO pools are parimutuel — winners split the losing pool pro-rata, minus a 2% protocol fee.</p>
          </div>
          <div className="legend-live"><span className="dot live" /> {markets.length} open</div>
        </div>
        <div className="grid">
          <div className="panel span8">
            <div className="p-head"><div className="ico">▦</div><h3>Open Markets</h3><span className="tag">tap to trade</span></div>
            <div className="markets">
              {markets.length > 0 ? (
                markets.map((m) => {
                  const y = impliedYes(m);
                  return (
                    <button className="mcard" key={m.id} onClick={() => setSelected(m)}>
                      <span className="cat" style={{ color: catColor(m.category), background: `color-mix(in srgb, ${catColor(m.category)} 12%, transparent)` }}>
                        {m.category}
                      </span>
                      <div className="mq">{m.question}</div>
                      <div className="odds">
                        <div className="chip yes"><div className="cn">YES</div><div className="co">{y}%</div></div>
                        <div className="chip no"><div className="cn">NO</div><div className="co">{100 - y}%</div></div>
                      </div>
                      <div className="mfoot"><span>{formatCompact(m.yes + m.no)} TVL</span><span>AI {Math.round(m.aiProbBps / 100)}%</span></div>
                    </button>
                  );
                })
              ) : (
                <p className="pos-empty" style={{ gridColumn: "1 / -1" }}>No open markets — run the relayer to create some.</p>
              )}
            </div>
          </div>
          <div className="panel span4">
            <div className="p-head"><div className="ico">◎</div><h3>Your Positions</h3><span className="tag">{positions.length}</span></div>
            {positions.length === 0 ? (
              <p className="pos-empty">No positions yet — open a market and place a demo trade.</p>
            ) : (
              positions.map((p, i) => (
                <div className="pos" key={i}>
                  <span className={`side ${p.side}`}>{p.side}</span>
                  <span className="pq">{p.question}</span>
                  <span className="pamt"><b>{money(p.stake)}</b> <span>→ {money(p.payout)}</span></span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      <TradeDrawer market={selected} onClose={() => setSelected(null)} onPlace={placePosition} />
      {toast && <div id="toast" className="show" role="status">{toast}</div>}
    </>
  );
}
