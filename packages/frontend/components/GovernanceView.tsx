"use client";
import { useState } from "react";
import type { GovernanceProposal } from "@oracleforge/shared/types";

type Vote = "f" | "a" | "ab" | null;
interface P {
  id: string;
  title: string;
  meta: string;
  f: number;
  a: number;
  ab: number;
  voted: Vote;
}

const ALLOC: Array<[string, number, string]> = [
  ["Protocol-owned liquidity", 38, "var(--cyan)"],
  ["Akash GPU reserve", 24, "var(--teal)"],
  ["Market incentives", 19, "var(--violet)"],
  ["Insurance / disputes", 12, "var(--ember)"],
  ["Operations", 7, "var(--faint)"],
];

function fromProposals(proposals: GovernanceProposal[]): P[] {
  if (proposals.length === 0) {
    return [
      { id: "OFP-47", title: "Allocate 1.2M $FORGE to Akash GPU reserve", meta: "quorum 68% reached · closes in 2d 06h", f: 72, a: 19, ab: 9, voted: null },
      { id: "OFP-46", title: "Lower market-creation fee 2.0% → 1.5%", meta: "quorum 71% reached · closes in 4d 11h", f: 58, a: 34, ab: 8, voted: null },
      { id: "OFP-45", title: "Add NOAA Chainlink Functions feed for climate markets", meta: "quorum 63% reached · closes in 1d 03h", f: 81, a: 11, ab: 8, voted: null },
    ];
  }
  return proposals.map((p) => {
    const f = Number(p.forVotes) || 0,
      a = Number(p.againstVotes) || 0,
      ab = Number(p.abstainVotes) || 0;
    const t = f + a + ab || 1;
    return {
      id: p.proposalId,
      title: p.title,
      meta: `quorum ${Math.round(p.quorumBps / 100)}% reached`,
      f: Math.round((f / t) * 100),
      a: Math.round((a / t) * 100),
      ab: Math.round((ab / t) * 100),
      voted: null,
    };
  });
}

export function GovernanceView({ proposals }: { proposals: GovernanceProposal[] }) {
  const [props, setProps] = useState<P[]>(() => fromProposals(proposals));
  const [toast, setToast] = useState<string | null>(null);

  function vote(i: number, v: "f" | "a" | "ab") {
    setProps((ps) =>
      ps.map((p, idx) => {
        if (idx !== i || p.voted) return p;
        const bumped = { ...p, [v]: Math.min(96, p[v] + 4), voted: v as Vote };
        const others = (["f", "a", "ab"] as const).filter((k) => k !== v);
        others.forEach((k) => (bumped[k] = Math.max(0, bumped[k] - 2)));
        const tot = bumped.f + bumped.a + bumped.ab;
        bumped.f = Math.round((bumped.f / tot) * 100);
        bumped.a = Math.round((bumped.a / tot) * 100);
        bumped.ab = 100 - bumped.f - bumped.a;
        return bumped;
      })
    );
    const label = v === "f" ? "FOR" : v === "a" ? "AGAINST" : "ABSTAIN";
    setToast(`Vote cast on ${props[i].id} · ${label} (1,000 $FORGE)`);
    window.setTimeout(() => setToast(null), 2600);
  }

  const rows: Array<["For" | "Against" | "Abstain", "f" | "a" | "ab", string]> = [
    ["For", "f", "var(--green)"],
    ["Against", "a", "var(--red)"],
    ["Abstain", "ab", "var(--faint)"],
  ];
  let off = 25;

  return (
    <div className="sec">
      <div className="sec-head">
        <div>
          <div className="eyebrow">Core Module 04</div>
          <h2>Treasury &amp; Governance</h2>
          <p>$FORGE holders steer the protocol. Cast a demo vote on an active proposal — tallies update live.</p>
        </div>
        <div className="legend-live"><span className="dot live" /> {props.length} active</div>
      </div>
      <div className="grid">
        <div className="panel span7">
          <div className="p-head"><div className="ico">⚖</div><h3>Active Proposals</h3><span className="tag">Gnosis DAO</span></div>
          {props.map((p, i) => (
            <div className="prop" key={p.id}>
              <div className="pt">{p.id} · {p.title}</div>
              <div className="pmeta">{p.meta}</div>
              {rows.map(([label, key, c]) => (
                <div className="vote" key={key}>
                  <span className="vl">{label}</span>
                  <div className="bar"><i style={{ width: `${p[key]}%`, background: c }} /></div>
                  <span className="vv">{p[key]}%</span>
                </div>
              ))}
              <div className="vbtns">
                <button className={`vbtn${p.voted === "f" ? " voted" : ""}`} onClick={() => vote(i, "f")}>Vote For</button>
                <button className={`vbtn${p.voted === "a" ? " voted" : ""}`} onClick={() => vote(i, "a")}>Against</button>
                <button className={`vbtn${p.voted === "ab" ? " voted" : ""}`} onClick={() => vote(i, "ab")}>Abstain</button>
              </div>
            </div>
          ))}
        </div>
        <div className="panel span5">
          <div className="p-head"><div className="ico">◭</div><h3>Treasury Allocation</h3><span className="tag">$48.7M</span></div>
          <div className="treas-row">
            <svg className="donut" viewBox="0 0 42 42">
              <circle cx="21" cy="21" r="15.9155" fill="none" stroke="var(--line)" strokeWidth={5} />
              {ALLOC.map(([, v, c]) => {
                const seg = <circle key={c} cx="21" cy="21" r="15.9155" fill="none" stroke={c} strokeWidth={5} strokeDasharray={`${v} ${100 - v}`} strokeDashoffset={off} />;
                off -= v;
                return seg;
              })}
              <text x="21" y="20" textAnchor="middle" fontFamily="var(--display)" fontWeight={700} fontSize={7} fill="var(--fg)">$48.7M</text>
              <text x="21" y="26" textAnchor="middle" fontFamily="var(--mono)" fontSize={3} fill="var(--faint)">TREASURY</text>
            </svg>
            <div className="alloc">
              {ALLOC.map(([n, v, c]) => (
                <div className="alloc-item" key={n}>
                  <span className="sw" style={{ background: c }} />
                  <span className="an">{n}</span>
                  <span className="av">{v}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      {toast && <div id="toast" className="show" role="status">{toast}</div>}
    </div>
  );
}
