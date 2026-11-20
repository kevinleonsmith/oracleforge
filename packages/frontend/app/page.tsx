import { getOpenMarkets, getProtocolStats, getActiveProposals, DATA_SOURCE } from "@/lib/api";
import { Terminal } from "@/components/Terminal";

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

      <Terminal markets={markets} proposals={proposals} />

      <p style={{ color: "var(--faint)", fontSize: 11, margin: "40px 0" }}>
        Demonstration interface. Markets, balances, trades and votes are simulated sample data —
        &ldquo;place position&rdquo; and &ldquo;vote&rdquo; are local demos; nothing is sent on-chain.
      </p>
    </main>
  );
}
