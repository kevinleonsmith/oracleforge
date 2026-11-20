import { getOpenMarkets, getProtocolStats, getActiveProposals, DATA_SOURCE } from "@/lib/api";
import { MarketCard } from "@/components/MarketCard";

const SOURCE_LABEL = DATA_SOURCE === "chain" ? "Live · Chiado" : "Sample data";

export default async function Home() {
  const [markets, stats, proposals] = await Promise.all([
    getOpenMarkets(),
    getProtocolStats(),
    getActiveProposals(),
  ]);

  return (
    <main className="wrap">
      <section className="hero">
        <span className="eyebrow">Autonomous · On-chain · Verifiable &nbsp;·&nbsp; {SOURCE_LABEL}</span>
        <h1>Autonomous Intelligence for <em>Predictive Markets</em></h1>
        <p>
          AI-generated prediction markets with deterministic off-chain compute and decentralized
          oracle settlement — on Cartesi, Chainlink, Gnosis, Arweave, Lit, Akash and Tableland.
        </p>
        <div className="stats">
          <div className="stat"><div className="k">Active Markets</div><div className="v">{stats.activeMarkets}</div></div>
          <div className="stat"><div className="k">Value Locked</div><div className="v">${(stats.tvlUsd / 1e6).toFixed(1)}M</div></div>
          <div className="stat"><div className="k">Avg AI Confidence</div><div className="v">{Math.round(stats.avgConfidenceBps / 100)}%</div></div>
          <div className="stat"><div className="k">Oracle Nodes</div><div className="v">{stats.oracleNodesOnline}/{stats.oracleNodesTotal}</div></div>
        </div>
      </section>

      <div className="grid">
        <div className="panel span8">
          <div className="p-head"><h3>Live Markets</h3></div>
          <div className="markets">
            {markets.length > 0 ? (
              markets.map((m) => <MarketCard key={m.marketId} m={m} />)
            ) : (
              <p style={{ color: "var(--muted)", fontSize: 13, gridColumn: "1 / -1" }}>
                No open markets found{DATA_SOURCE === "chain" ? " on-chain yet — run the relayer to create some." : "."}
              </p>
            )}
          </div>
        </div>
        <div className="panel span4">
          <div className="p-head"><h3>Governance</h3></div>
          {proposals.map((p) => (
            <div key={p.proposalId}>
              <div style={{ fontSize: 13, fontWeight: 500 }}>{p.proposalId} · {p.title}</div>
              <div className="mono" style={{ fontSize: 10, color: "var(--faint)", margin: "4px 0 12px" }}>
                quorum {Math.round(p.quorumBps / 100)}% reached
              </div>
              {([["For", p.forVotes, "var(--green)"], ["Against", p.againstVotes, "var(--red)"], ["Abstain", p.abstainVotes, "var(--faint)"]] as const).map(([label, v, c]) => (
                <div key={label} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12, marginBottom: 7 }}>
                  <span style={{ width: 52, color: "var(--muted)" }}>{label}</span>
                  <div style={{ flex: 1, height: 6, borderRadius: 4, background: "var(--line)", overflow: "hidden" }}>
                    <i style={{ display: "block", height: "100%", width: `${v}%`, background: c }} />
                  </div>
                  <span className="mono" style={{ width: 36, textAlign: "right" }}>{v}%</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      <p style={{ color: "var(--faint)", fontSize: 11, margin: "40px 0" }}>
        Demonstration interface. Markets, balances and forecasts are simulated sample data.
      </p>
    </main>
  );
}
