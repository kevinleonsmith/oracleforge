"use client";
import { useEffect, useState } from "react";
import type { Market, GovernanceProposal } from "@oracleforge/shared/types";
import { MarketsView } from "./MarketsView";
import { SimulationExplorer } from "./SimulationExplorer";
import { GovernanceView } from "./GovernanceView";

const VIEWS = ["markets", "simulations", "governance"] as const;
type View = (typeof VIEWS)[number];

export function Terminal({
  markets,
  proposals,
}: {
  markets: Market[];
  proposals: GovernanceProposal[];
}) {
  const [view, setView] = useState<View>("markets");

  // hash routing: #markets | #simulations | #governance
  useEffect(() => {
    const sync = () => {
      const h = window.location.hash.slice(1) as View;
      setView(VIEWS.includes(h) ? h : "markets");
    };
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const go = (v: View) => {
    window.location.hash = v;
    setView(v);
  };

  return (
    <>
      <nav className="tabs" style={{ paddingTop: 20 }}>
        {VIEWS.map((v) => (
          <button key={v} className={`tab${view === v ? " active" : ""}`} onClick={() => go(v)}>
            {v[0].toUpperCase() + v.slice(1)}
          </button>
        ))}
      </nav>

      {view === "markets" && <MarketsView initialMarkets={markets} />}
      {view === "simulations" && <SimulationExplorer markets={markets} />}
      {view === "governance" && <GovernanceView proposals={proposals} />}
    </>
  );
}
