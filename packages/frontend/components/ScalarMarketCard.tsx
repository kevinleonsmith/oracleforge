"use client";
import { useState, type CSSProperties } from "react";
import {
  impliedValue,
  bandPercent,
  scalarPayoutPreview,
  type ScalarSide,
} from "@/lib/scalar";
import { catColor } from "@/lib/ui";

// A scalar (range) market tile: shows the band, the pools' implied settlement
// value, and — as you drag a hypothetical settlement point — the live LONG/SHORT
// payout for a demo stake. The math is lib/scalar (mirrors the contract); this
// just paints it. Demo only, nothing is sent on-chain.

export interface ScalarMarketData {
  id: string;
  category: string;
  question: string;
  feed: string;
  lower: number;
  upper: number;
  unit: string; // e.g. "$", "%", "" — how to render band numbers
  longPool: number;
  shortPool: number;
}

const DEMO_STAKE = 100;

const fmt = (n: number, unit: string) => {
  const v = Math.abs(n) >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${Math.round(n)}`;
  return unit === "$" ? `$${v}` : unit === "%" ? `${v}%` : v;
};

export function ScalarMarketCard({ m }: { m: ScalarMarketData }) {
  const implied = impliedValue(m.lower, m.upper, m.longPool, m.shortPool);
  const [atValue, setAtValue] = useState(Math.round(implied));

  const impliedPct = bandPercent(m.lower, m.upper, implied);
  const atPct = bandPercent(m.lower, m.upper, atValue);
  const previewLong = scalarPayoutPreview(m.lower, m.upper, m.longPool, m.shortPool, "LONG", DEMO_STAKE, atValue);
  const previewShort = scalarPayoutPreview(m.lower, m.upper, m.longPool, m.shortPool, "SHORT", DEMO_STAKE, atValue);

  const pill = (side: ScalarSide) => {
    const p = side === "LONG" ? previewLong : previewShort;
    const color = side === "LONG" ? "var(--green)" : "var(--red)";
    const up = p.profit >= 0;
    const box: CSSProperties = {
      flex: 1, border: "1px solid var(--line)", borderRadius: 7, padding: "7px 9px",
      background: "var(--panel-2)",
    };
    return (
      <div style={box}>
        <div className="mono" style={{ fontSize: 10, color, letterSpacing: ".08em" }}>{side}</div>
        <div style={{ fontFamily: "var(--display)", fontWeight: 600, fontSize: 15 }}>
          {fmt(p.payout, "")} <span className="mono" style={{ fontSize: 10, color: "var(--faint)" }}>on {DEMO_STAKE}</span>
        </div>
        <div className="mono" style={{ fontSize: 10, color: up ? "var(--green)" : "var(--red)" }}>
          {up ? "+" : ""}{p.roi.toFixed(0)}% ROI
        </div>
      </div>
    );
  };

  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 9, padding: 12, background: "var(--panel)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7, flexWrap: "wrap" }}>
        <span className="cat" style={{ color: catColor(m.category), background: `color-mix(in srgb, ${catColor(m.category)} 12%, transparent)` }}>
          {m.category}
        </span>
        <span className="mono" style={{ fontSize: 10, color: "var(--faint)" }}>SCALAR · {m.feed}</span>
      </div>
      <div style={{ fontSize: 13, marginBottom: 11, lineHeight: 1.32 }}>{m.question}</div>

      {/* band with implied marker + a draggable settlement point */}
      <div style={{ position: "relative", height: 8, borderRadius: 5, background: "var(--panel-2)", border: "1px solid var(--line)", marginBottom: 6 }}>
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${atPct}%`, background: "color-mix(in srgb, var(--green) 30%, transparent)", borderRadius: 5 }} />
        {/* implied-value marker */}
        <div title="market-implied value" style={{ position: "absolute", left: `${impliedPct}%`, top: -3, width: 2, height: 14, background: "var(--cyan)", transform: "translateX(-1px)" }} />
      </div>
      <input
        type="range"
        min={m.lower}
        max={m.upper}
        step={Math.max(1, (m.upper - m.lower) / 100)}
        value={atValue}
        onChange={(e) => setAtValue(Number(e.target.value))}
        aria-label="hypothetical settlement value"
        style={{ width: "100%", accentColor: "var(--green)" }}
      />
      <div className="mono" style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--faint)", marginTop: 2 }}>
        <span>{fmt(m.lower, m.unit)}</span>
        <span style={{ color: "var(--cyan)" }}>implied {fmt(implied, m.unit)}</span>
        <span>{fmt(m.upper, m.unit)}</span>
      </div>

      <div className="mono" style={{ fontSize: 11, textAlign: "center", margin: "9px 0 8px" }}>
        if it settles at <b style={{ color: "var(--text)" }}>{fmt(atValue, m.unit)}</b>
      </div>
      <div style={{ display: "flex", gap: 7 }}>
        {pill("LONG")}
        {pill("SHORT")}
      </div>
      <div className="mono" style={{ fontSize: 10, color: "var(--faint)", marginTop: 8, display: "flex", justifyContent: "space-between" }}>
        <span>LONG pool {fmt(m.longPool, "")}</span>
        <span>SHORT pool {fmt(m.shortPool, "")}</span>
      </div>
    </div>
  );
}
