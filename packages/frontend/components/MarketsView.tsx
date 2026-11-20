"use client";
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import type { Market } from "@oracleforge/shared/types";
import { formatCompact } from "@/lib/format";
import { catColor, toUiMarket, type Position, type UiMarket } from "@/lib/ui";
import type { ResolutionInput } from "@/lib/dispute";
import { ChallengeStatus } from "./ChallengeStatus";
import { ScalarMarketCard, type ScalarMarketData } from "./ScalarMarketCard";
import { ProbabilityChart } from "./ProbabilityChart";
import { TradeDrawer } from "./TradeDrawer";

// Sample scalar (range) markets for the demo. Static -> deterministic server
// render (the cards' slider seeds from the pools, so no hydration mismatch).
const SCALAR_MARKETS: ScalarMarketData[] = [
  { id: "MKT-0xE71", category: "CRYPTO", question: "Where will ETH close at the end of the quarter?", feed: "ETH/USD", lower: 3000, upper: 5000, unit: "$", longPool: 620, shortPool: 380 },
  { id: "MKT-0xC90", category: "MACRO", question: "US CPI year-over-year for the reference month?", feed: "ECON/CPI", lower: 2, upper: 5, unit: "%", longPool: 300, shortPool: 500 },
  { id: "MKT-0xB44", category: "CRYPTO", question: "Average Gnosis gas price over the settlement window?", feed: "GAS/GWEI", lower: 0, upper: 50, unit: "", longPool: 450, shortPool: 450 },
];

const DEMO_CHALLENGER = "0x7F3aC9d2E1b84465A0cE9f21D8b7c0F3aE62d410";

interface DisputeDemo {
  id: string;
  category: string;
  question: string;
  input: Omit<ResolutionInput, "now">;
}

// Client-only demo of the optimistic-resolution window — one market in each
// phase. Seeded in an effect (never during SSR) so the live countdown anchors to
// the viewer's clock with no hydration mismatch. The window/outcome fields are
// exactly what readDisputeState() returns from the chain on a live deployment.
function buildDisputeDemo(nowSec: number): DisputeDemo[] {
  const WINDOW = 3600; // 1h challenge window
  const base = { challengeWindow: WINDOW, status: "CLOSED" as const };
  return [
    {
      id: "MKT-0x5C1A",
      category: "CRYPTO",
      question: "Did ETH close above $4,000 on the settlement date?",
      input: { ...base, proposedAt: nowSec - 90, proposedOutcome: 1, challenger: "" }, // YES, in window
    },
    {
      id: "MKT-0x9E22",
      category: "MACRO",
      question: "Was US unemployment at or below 4.0% for the reference month?",
      input: { ...base, proposedAt: nowSec - 1800, proposedOutcome: 2, challenger: DEMO_CHALLENGER }, // NO, disputed
    },
    {
      id: "MKT-0x3B07",
      category: "GEO",
      question: "Did the referendum pass with a majority of valid votes?",
      input: { ...base, proposedAt: nowSec - 7200, proposedOutcome: 1, challenger: "" }, // YES, window elapsed
    },
  ];
}

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
  const [disputes, setDisputes] = useState<DisputeDemo[]>([]);
  const series = useMemo(demoSeries, []);
  const confAvg = Math.round(CONFIDENCE.reduce((a, c) => a + c[1], 0) / CONFIDENCE.length);

  // Seed the dispute demo client-side (anchors the countdown to the viewer's clock).
  useEffect(() => setDisputes(buildDisputeDemo(Math.floor(Date.now() / 1000))), []);

  function flash(msg: string) {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2600);
  }

  function fileDispute(id: string) {
    // Move the challenged market into the frozen "disputed" phase, as dispute() would.
    setDisputes((ds) =>
      ds.map((d) => (d.id === id ? { ...d, input: { ...d.input, challenger: DEMO_CHALLENGER } } : d))
    );
    flash(`Dispute filed · 100 ofUSD bond posted on ${id} — frozen for arbitration`);
  }

  function finalizeDispute(id: string) {
    setDisputes((ds) => ds.filter((d) => d.id !== id));
    flash(`Finalized ${id} — outcome locked, claims open`);
  }

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

      {/* Scalar (range) markets */}
      <div className="sec">
        <div className="sec-head">
          <div>
            <div className="eyebrow">New Market Type</div>
            <h2>Scalar (Range) Markets</h2>
            <p>
              Numeric questions settled along a continuum, not yes/no. Traders take LONG or SHORT on
              a band; at settlement the pot is split by where the oracle value lands. Drag a market to
              see the LONG/SHORT payout at any settlement point.
            </p>
          </div>
          <div className="legend-live"><span className="dot live" /> {SCALAR_MARKETS.length} ranges</div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 11 }}>
          {SCALAR_MARKETS.map((sm) => (
            <ScalarMarketCard key={sm.id} m={sm} />
          ))}
        </div>
      </div>

      {/* Optimistic resolution */}
      {disputes.length > 0 && (
        <div className="sec">
          <div className="sec-head">
            <div>
              <div className="eyebrow">Settlement Layer</div>
              <h2>Optimistic Resolution</h2>
              <p>
                When a market closes, the oracle&apos;s outcome is <em>proposed</em>, not final. It
                must survive a challenge window — anyone can post a bond to dispute it, which freezes
                the market for admin arbitration — before <code>finalize()</code> opens claims.
              </p>
            </div>
            <div className="legend-live"><span className="dot live" /> {disputes.length} in review</div>
          </div>
          <div className="panel">
            <div className="p-head"><div className="ico">⚖</div><h3>Proposed Outcomes</h3><span className="tag">challenge · dispute · finalize</span></div>
            <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
              {disputes.map((d) => (
                <div key={d.id} style={{ border: "1px solid var(--line)", borderRadius: 9, padding: 11, background: "var(--panel-2)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 8, flexWrap: "wrap" }}>
                    <span className="cat" style={{ color: catColor(d.category), background: `color-mix(in srgb, ${catColor(d.category)} 12%, transparent)` }}>
                      {d.category}
                    </span>
                    <span className="mono" style={{ fontSize: 10, color: "var(--faint)" }}>{d.id}</span>
                    <span style={{ fontSize: 12.5 }}>{d.question}</span>
                  </div>
                  <ChallengeStatus
                    input={d.input}
                    bondLabel="100 ofUSD"
                    onDispute={() => fileDispute(d.id)}
                    onFinalize={() => finalizeDispute(d.id)}
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <TradeDrawer market={selected} onClose={() => setSelected(null)} onPlace={placePosition} />
      {toast && <div id="toast" className="show" role="status">{toast}</div>}
    </>
  );
}
