"use client";
import { useEffect, useState } from "react";
import { payoutPreview, formatCompact } from "@/lib/format";
import { catColor, type UiMarket, type Position } from "@/lib/ui";

const money = (n: number) => (n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${n.toFixed(0)}`);

export function TradeDrawer({
  market,
  onClose,
  onPlace,
}: {
  market: UiMarket | null;
  onClose: () => void;
  onPlace: (p: Position) => void;
}) {
  const [side, setSide] = useState<"YES" | "NO">("YES");
  const [stake, setStake] = useState(100);

  // reset when a new market opens; close on Escape
  useEffect(() => {
    if (market) {
      setSide("YES");
      setStake(100);
    }
  }, [market]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && market) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [market, onClose]);

  const open = market !== null;
  const p = market ? payoutPreview(market.yes, market.no, side, stake) : null;
  const impliedYes = market ? Math.round((market.yes / (market.yes + market.no || 1)) * 100) : 50;

  function place() {
    if (!market || stake <= 0 || !p) return;
    onPlace({ id: market.id, question: market.question, side, stake, payout: p.payout });
  }

  return (
    <>
      <div className={`scrim${open ? " open" : ""}`} hidden={!open} onClick={onClose} />
      <aside className={`drawer${open ? " open" : ""}`} hidden={!open} aria-label="Trade market">
        {market && (
          <>
            <div className="dw-top">
              <span
                className="dw-cat"
                style={{
                  fontFamily: "var(--mono)",
                  fontSize: 10,
                  letterSpacing: ".1em",
                  textTransform: "uppercase",
                  padding: "2px 7px",
                  borderRadius: 5,
                  color: catColor(market.category),
                  background: `color-mix(in srgb, ${catColor(market.category)} 12%, transparent)`,
                }}
              >
                {market.category}
              </span>
              <button className="dw-close" aria-label="Close" onClick={onClose}>
                ✕
              </button>
            </div>
            <div className="dw-q">{market.question}</div>
            <div className="dw-meta">
              MKT-{market.id} · {formatCompact(market.yes + market.no)} TVL · settles via Chainlink
            </div>

            <div className="side-toggle">
              <button className={`YES${side === "YES" ? " sel" : ""}`} onClick={() => setSide("YES")}>
                <span className="st-n">YES</span>
                <span className="st-o">{impliedYes}%</span>
              </button>
              <button className={`NO${side === "NO" ? " sel" : ""}`} onClick={() => setSide("NO")}>
                <span className="st-n">NO</span>
                <span className="st-o">{100 - impliedYes}%</span>
              </button>
            </div>

            <div className="stake-field">
              <label htmlFor="dw-stake">STAKE</label>
              <div className="stake-input">
                <input
                  id="dw-stake"
                  type="number"
                  min={0}
                  step={10}
                  value={stake}
                  inputMode="decimal"
                  onChange={(e) => setStake(Math.max(0, parseFloat(e.target.value) || 0))}
                />
                <span className="cur">WXDAI</span>
              </div>
              <div className="quick">
                {[50, 100, 500, 1000].map((a) => (
                  <button key={a} onClick={() => setStake(a)}>
                    {a.toLocaleString()}
                  </button>
                ))}
              </div>
            </div>

            {p && (
              <div className="payout">
                <div className="prow">
                  <span className="k">Side</span>
                  <span className="v">{side} @ {market.id}</span>
                </div>
                <div className="prow">
                  <span className="k">Avg price (implied)</span>
                  <span className="v">{Math.round(p.pricePct)}% implied</span>
                </div>
                <div className="prow">
                  <span className="k">Net profit if correct</span>
                  <span className="v roi">+{money(p.profit)}</span>
                </div>
                <div className="prow">
                  <span className="k">ROI</span>
                  <span className="v roi">+{p.roi.toFixed(0)}%</span>
                </div>
                <div className="prow big">
                  <span className="k">Payout if correct</span>
                  <span className="v">{money(p.payout)}</span>
                </div>
              </div>
            )}

            <button className="btn primary" style={{ width: "100%", padding: 13, fontSize: 14 }} disabled={stake <= 0} onClick={place}>
              Place Position
            </button>
            <div className="dw-note">
              Parimutuel settlement · 2% protocol fee from the losing pool · deterministic Chainlink resolution at close.
              Demo only — no wallet, no on-chain transaction.
            </div>
          </>
        )}
      </aside>
    </>
  );
}
