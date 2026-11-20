// Pure SVG probability chart (shared by the prediction engine + simulation views).
// Renders a line + sigma band + emphasized endpoint from a 0..1 series.

const DEFAULT_XLABELS: Array<[string, number]> = [
  ["14d", 0],
  ["10d", 0.29],
  ["6d", 0.58],
  ["2d", 0.87],
  ["now", 1],
];

export function ProbabilityChart({
  data,
  marketLine,
  sigma = 0.06,
  xlabels = DEFAULT_XLABELS,
  ariaLabel,
}: {
  data: number[];
  marketLine?: number[];
  sigma?: number;
  xlabels?: Array<[string, number]>;
  ariaLabel?: string;
}) {
  const W = 680,
    H = 250,
    m = { l: 34, r: 48, t: 16, b: 26 };
  const iw = W - m.l - m.r,
    ih = H - m.t - m.b,
    N = data.length;
  if (N < 2) return null;
  const X = (i: number) => m.l + (i / (N - 1)) * iw;
  const Y = (v: number) => m.t + (1 - v) * ih;
  const path = (a: number[]) =>
    a.map((v, i) => (i ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1)).join(" ");

  const gridLines = [0, 0.25, 0.5, 0.75, 1];
  const top = data.map((v, i) => [X(i), Y(Math.min(0.97, v + sigma))] as const);
  const bot = data.map((v, i) => [X(i), Y(Math.max(0.03, v - sigma))] as const).reverse();
  const band =
    "M" +
    top.map((p) => p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" L ") +
    " L " +
    bot.map((p) => p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" L ") +
    " Z";
  const last = data[N - 1],
    ex = X(N - 1),
    ey = Y(last);

  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel ?? `probability ${Math.round(last * 100)} percent`}>
        {gridLines.map((v) => {
          const y = Y(v);
          return (
            <g key={v}>
              <line
                x1={m.l}
                y1={y}
                x2={m.l + iw}
                y2={y}
                stroke="var(--line)"
                strokeWidth={1}
                strokeDasharray={v === 0 || v === 1 ? undefined : "2 4"}
              />
              <text x={m.l - 8} y={y + 3} textAnchor="end" fontFamily="var(--mono)" fontSize={10} fill="var(--faint)">
                {v * 100}
              </text>
            </g>
          );
        })}
        {xlabels.map(([t, f], i) => (
          <text
            key={i}
            x={m.l + f * iw}
            y={H - 8}
            textAnchor={f === 1 ? "end" : f === 0 ? "start" : "middle"}
            fontFamily="var(--mono)"
            fontSize={10}
            fill="var(--faint)"
          >
            {t}
          </text>
        ))}
        <path d={band} fill="var(--cyan)" opacity={0.08} />
        {marketLine && (
          <path d={path(marketLine)} fill="none" stroke="var(--violet)" strokeWidth={1.6} strokeOpacity={0.55} strokeDasharray="3 3" />
        )}
        <path d={path(data)} fill="none" stroke="var(--cyan)" strokeWidth={2.4} strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={ex} cy={ey} r={4.5} fill="var(--cyan)" />
        <circle cx={ex} cy={ey} r={8} fill="none" stroke="var(--cyan)" strokeOpacity={0.4} />
        <line x1={ex} y1={m.t} x2={ex} y2={m.t + ih} stroke="var(--cyan)" strokeWidth={1} strokeOpacity={0.25} />
      </svg>
    </div>
  );
}
