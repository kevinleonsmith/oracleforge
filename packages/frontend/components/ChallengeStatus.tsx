"use client";
import { useEffect, useState, type CSSProperties } from "react";
import {
  disputePhase,
  formatCountdown,
  type ResolutionInput,
  type ResolutionPhase,
} from "@/lib/dispute";

// Renders a market's optimistic-resolution phase with a live countdown. The pure
// phase logic lives in lib/dispute; this component just supplies a ticking `now`
// and paints each state. onDispute/onFinalize are demo callbacks (the app sends
// nothing on-chain) — on a live deployment they'd be the dispute()/finalize() txs.

const shortAddr = (a: string) => (a.length > 12 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a);

const pill: CSSProperties = {
  fontFamily: "var(--mono)",
  fontSize: 11,
  letterSpacing: ".04em",
  border: "1px solid var(--line)",
  borderRadius: 8,
  padding: "8px 11px",
  display: "flex",
  alignItems: "center",
  gap: 10,
  flexWrap: "wrap",
};

const btn: CSSProperties = {
  fontFamily: "var(--mono)",
  fontSize: 11,
  padding: "4px 10px",
  borderRadius: 6,
  border: "1px solid var(--line)",
  background: "var(--panel-2)",
  color: "var(--text)",
  cursor: "pointer",
  marginLeft: "auto",
};

export interface ChallengeStatusProps {
  input: Omit<ResolutionInput, "now">;
  bondLabel?: string; // e.g. "100 ofUSD" — what a dispute costs
  onDispute?: () => void;
  onFinalize?: () => void;
}

export function ChallengeStatus({ input, bondLabel, onDispute, onFinalize }: ChallengeStatusProps) {
  // Re-tick every second so the countdown stays live; the pure function is the
  // single source of truth, we just feed it a fresh `now`. First paint is seeded
  // deterministically from `proposedAt` (identical on server and client, so no
  // hydration mismatch); the effect snaps it to real time on mount, then ticks.
  const [now, setNow] = useState(input.proposedAt);
  useEffect(() => {
    const tick = () => setNow(Math.floor(Date.now() / 1000));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, []);

  const phase: ResolutionPhase = disputePhase({ ...input, now });
  if (phase.kind === "none") return null;

  if (phase.kind === "challenge") {
    return (
      <div style={{ ...pill, borderColor: "var(--ember)", color: "var(--ember)" }}>
        <span>⚠ CHALLENGE WINDOW</span>
        <span style={{ color: "var(--faint)" }}>
          proposed <b style={{ color: "var(--text)" }}>{phase.outcome}</b> · closes in{" "}
          <b style={{ color: "var(--ember)" }}>{formatCountdown(phase.secondsLeft)}</b>
        </span>
        {onDispute && (
          <button style={btn} onClick={onDispute}>
            Dispute{bondLabel ? ` · ${bondLabel}` : ""}
          </button>
        )}
      </div>
    );
  }

  if (phase.kind === "disputed") {
    return (
      <div style={{ ...pill, borderColor: "var(--red)", color: "var(--red)" }}>
        <span>⛔ DISPUTED</span>
        <span style={{ color: "var(--faint)" }}>
          frozen — awaiting arbitration · challenger{" "}
          <b style={{ color: "var(--text)" }}>{shortAddr(phase.challenger)}</b>
        </span>
      </div>
    );
  }

  // finalizable
  return (
    <div style={{ ...pill, borderColor: "var(--green)", color: "var(--green)" }}>
      <span>✓ READY TO FINALIZE</span>
      <span style={{ color: "var(--faint)" }}>
        window elapsed · proposed <b style={{ color: "var(--text)" }}>{phase.outcome}</b>
      </span>
      {onFinalize && (
        <button style={btn} onClick={onFinalize}>
          Finalize
        </button>
      )}
    </div>
  );
}
