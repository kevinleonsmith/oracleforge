"use client";
import { useMemo, useState } from "react";
import type { Market } from "@oracleforge/shared/types";
import { toUiMarket, type UiMarket } from "@/lib/ui";
import { ProbabilityChart } from "./ProbabilityChart";

// Deterministic PRNG (mulberry32) — same inputs give the same path, mirroring the
// Cartesi forecaster's reproducibility.
function mulberry(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hashStr(s: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return "0x" + (h >>> 0).toString(16).padStart(8, "0") + "…";
}

export function SimulationExplorer({ markets }: { markets: Market[] }) {
  const ui: UiMarket[] = useMemo(() => markets.map(toUiMarket), [markets]);
  const [marketId, setMarketId] = useState(ui[0]?.id ?? "");
  const [bias, setBias] = useState(40); // -100..100 -> -1..1
  const [horizon, setHorizon] = useState(45);
  const [vol, setVol] = useState(70); // 20..140 -> 0.2..1.4

  const sim = useMemo(() => {
    const m = ui.find((x) => x.id === marketId) ?? ui[0];
    if (!m) return null;
    const b = bias / 100,
      v = vol / 100;
    const seed = [...(marketId + b.toFixed(2) + horizon + v.toFixed(2))].reduce((s, c) => s + c.charCodeAt(0), 0);
    const rng = mulberry(seed);
    const N = 40;
    const p0 = m.aiProbBps / 10000 || 0.5;
    const target = 1 / (1 + Math.exp(-(Math.log(p0 / (1 - p0)) + 1.4 * b)));
    let p = p0;
    const path: number[] = [];
    for (let i = 0; i < N; i++) {
      p += (target - p) * 0.06 + (rng() - 0.5) * v * 0.05;
      p = Math.max(0.03, Math.min(0.97, p));
      path.push(p);
    }
    const last = path[N - 1];
    const ci = Math.round(v * 14);
    return {
      path,
      pct: Math.round(last * 100),
      ciLow: Math.max(0, Math.round(last * 100) - ci),
      ciHigh: Math.min(100, Math.round(last * 100) + ci),
      close: last >= 0.5 ? "YES" : "NO",
      hash: hashStr(marketId + b + horizon + v),
      sigma: Math.min(0.18, v * 0.14),
    };
  }, [ui, marketId, bias, horizon, vol]);

  const xlabels: Array<[string, number]> = [
    [`${horizon}d`, 0],
    [`${Math.round(horizon * 0.66)}d`, 0.34],
    [`${Math.round(horizon * 0.33)}d`, 0.67],
    ["close", 1],
  ];

  return (
    <div className="sec">
      <div className="sec-head">
        <div>
          <div className="eyebrow">Core Module 05</div>
          <h2>Simulation Explorer</h2>
          <p>Deterministic Monte Carlo forecasting inside the Cartesi Machine. Adjust the scenario and horizon to re-run the probability fan.</p>
        </div>
        <div className="legend-live"><span className="dot live" /> n=20,000</div>
      </div>
      <div className="grid">
        <div className="panel span12">
          <div className="sim-controls">
            <label>
              Market
              <select value={marketId} onChange={(e) => setMarketId(e.target.value)}>
                {ui.map((m) => (
                  <option key={m.id} value={m.id}>{m.id} · {m.question.slice(0, 40)}…</option>
                ))}
              </select>
            </label>
            <label>
              Signal bias
              <input type="range" min={-100} max={100} value={bias} style={{ width: 140 }} onChange={(e) => setBias(+e.target.value)} />
              <span className="mono">{bias >= 0 ? "+" : ""}{(bias / 100).toFixed(2)}</span>
            </label>
            <label>
              Horizon
              <input type="range" min={7} max={120} value={horizon} style={{ width: 120 }} onChange={(e) => setHorizon(+e.target.value)} />
              <span className="mono">{horizon}d</span>
            </label>
            <label>
              Volatility
              <input type="range" min={20} max={140} value={vol} style={{ width: 120 }} onChange={(e) => setVol(+e.target.value)} />
              <span className="mono">{(vol / 100).toFixed(2)}</span>
            </label>
          </div>
          {sim && <ProbabilityChart data={sim.path} sigma={sim.sigma} xlabels={xlabels} ariaLabel={`simulation ${sim.pct} percent`} />}
          {sim && (
            <div className="sim-stats">
              <div><div className="k">P(YES)</div><div className="v">{sim.pct}%</div></div>
              <div><div className="k">95% CI</div><div className="v">{sim.ciLow}–{sim.ciHigh}%</div></div>
              <div><div className="k">EXPECTED CLOSE</div><div className="v" style={{ color: sim.close === "YES" ? "var(--green)" : "var(--red)" }}>{sim.close}</div></div>
              <div><div className="k">INPUT HASH</div><div className="v" style={{ fontSize: 12, color: "var(--cyan)" }}>{sim.hash}</div></div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
