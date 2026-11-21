"use client";
import { useState, type CSSProperties } from "react";
import {
  impliedProbabilities,
  categoricalPayoutPreview,
  favorite,
  type CategoricalOutcome,
} from "@/lib/categorical";
import { catColor } from "@/lib/ui";

// A categorical (N-outcome) market tile: shows each outcome's pool, its
// book-implied probability, and — when you pick an outcome — the live
// winner-take-all payout for a demo stake. The math is lib/categorical (mirrors
// CategoricalMarketEngine); this just paints it. Demo only, nothing on-chain.

export interface CategoricalMarketData {
  id: string;
  category: string;
  question: string;
  feed: string;
  outcomes: CategoricalOutcome[];
}

const DEMO_STAKE = 100;

// A small fixed palette for the outcome bars — identity by position, not rank,
// and never color-alone (every bar carries its label + percentage).
const OUTCOME_COLORS = ["var(--cyan)", "var(--violet)", "var(--ember)", "var(--teal)", "var(--green)", "var(--red)"];
const outcomeColor = (i: number) => OUTCOME_COLORS[i % OUTCOME_COLORS.length];

const fmt = (n: number) => (Math.abs(n) >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${Math.round(n)}`);

export function CategoricalMarketCard({ m }: { m: CategoricalMarketData }) {
  const probs = impliedProbabilities(m.outcomes);
  const lead = favorite(m.outcomes);
  // Default the payout preview to the current front-runner (or the first outcome).
  const [picked, setPicked] = useState(lead >= 0 ? lead : 0);

  const preview = categoricalPayoutPreview(m.outcomes, picked, DEMO_STAKE);
  const pot = m.outcomes.reduce((a, o) => a + o.pool, 0);
  const up = preview.profit >= 0;

  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 9, padding: 12, background: "var(--panel)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7, flexWrap: "wrap" }}>
        <span className="cat" style={{ color: catColor(m.category), background: `color-mix(in srgb, ${catColor(m.category)} 12%, transparent)` }}>
          {m.category}
        </span>
        <span className="mono" style={{ fontSize: 10, color: "var(--faint)" }}>
          CATEGORICAL · {m.outcomes.length}-way · {m.feed}
        </span>
      </div>
      <div style={{ fontSize: 13, marginBottom: 11, lineHeight: 1.32 }}>{m.question}</div>

      {/* one row per outcome: label · implied-probability bar · click to price it */}
      <div style={{ display: "flex", flexDirection: "column", gap: 5, marginBottom: 10 }}>
        {m.outcomes.map((o, i) => {
          const pct = Math.round(probs[i] * 100);
          const active = i === picked;
          const color = outcomeColor(i);
          const row: CSSProperties = {
            display: "grid", gridTemplateColumns: "1fr auto", gap: 6, alignItems: "center",
            width: "100%", textAlign: "left", cursor: "pointer",
            border: `1px solid ${active ? color : "var(--line)"}`, borderRadius: 7,
            padding: "6px 8px", background: active ? `color-mix(in srgb, ${color} 10%, transparent)` : "var(--panel-2)",
          };
          return (
            <button key={o.label} style={row} onClick={() => setPicked(i)} aria-pressed={active}
              aria-label={`Price ${o.label}, implied ${pct} percent`}>
              <div style={{ minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: color, flex: "0 0 auto" }} />
                  <span style={{ fontSize: 12, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{o.label}</span>
                </div>
                {/* implied-probability bar */}
                <div style={{ height: 5, borderRadius: 3, background: "var(--panel)", overflow: "hidden" }}>
                  <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3 }} />
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div className="mono" style={{ fontSize: 13, fontWeight: 600, color: active ? color : "var(--text)" }}>{pct}%</div>
                <div className="mono" style={{ fontSize: 9, color: "var(--faint)" }}>{fmt(o.pool)} pool</div>
              </div>
            </button>
          );
        })}
      </div>

      {/* payout preview for the picked outcome */}
      <div className="mono" style={{ fontSize: 11, textAlign: "center", marginBottom: 7 }}>
        back <b style={{ color: outcomeColor(picked) }}>{m.outcomes[picked]?.label}</b> with {DEMO_STAKE} — if it wins
      </div>
      <div style={{ border: "1px solid var(--line)", borderRadius: 7, padding: "8px 10px", background: "var(--panel-2)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        {preview.voids ? (
          <span className="mono" style={{ fontSize: 11, color: "var(--faint)" }}>
            sole funded outcome → <b style={{ color: "var(--text)" }}>void</b>, stake refunded
          </span>
        ) : (
          <>
            <div style={{ fontFamily: "var(--display)", fontWeight: 600, fontSize: 16 }}>
              {fmt(preview.payout)} <span className="mono" style={{ fontSize: 10, color: "var(--faint)" }}>payout</span>
            </div>
            <div className="mono" style={{ fontSize: 12, color: up ? "var(--green)" : "var(--red)", textAlign: "right" }}>
              {up ? "+" : ""}{preview.profit.toFixed(0)} · {up ? "+" : ""}{preview.roi.toFixed(0)}% ROI
            </div>
          </>
        )}
      </div>

      <div className="mono" style={{ fontSize: 10, color: "var(--faint)", marginTop: 8, display: "flex", justifyContent: "space-between" }}>
        <span>pot {fmt(pot)}</span>
        <span>winner-take-all · 2% fee</span>
      </div>
    </div>
  );
}
