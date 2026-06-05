import type { CSSProperties } from "react";

/**
 * Animated "intelligence core" visual for the landing hero.
 *
 * Story (matches the product vision): scattered data sources — databases and
 * the codebase — stream their context inward to a central intelligence core,
 * which emits a verified, charted answer.
 *
 * Implementation: pure SVG + CSS animations (token-driven, GPU-safe). No JS,
 * no image assets. All motion is neutralized under prefers-reduced-motion via
 * the global rule in globals.css. The whole graphic is decorative and is
 * hidden from assistive tech (`aria-hidden`) — the hero conveys meaning in
 * text.
 */

type SourceNode = {
  id: string;
  label: string;
  /** Center point of the node box. */
  x: number;
  y: number;
  /** Semantic color token for the node accent dot + edge. */
  color: string;
  /** Stagger for flow + pulse timing. */
  delay: number;
};

const CORE = { x: 292, y: 230 };
const ANSWER_IN = { x: 472, y: 230 };

const NODE_W = 132;
const NODE_H = 38;

const SOURCES: SourceNode[] = [
  { id: "pg", label: "PostgreSQL", x: 86, y: 92, color: "var(--color-accent)", delay: 0 },
  { id: "ch", label: "ClickHouse", x: 78, y: 230, color: "var(--color-info)", delay: 0.8 },
  { id: "my", label: "MySQL", x: 86, y: 368, color: "var(--color-accent-hover)", delay: 1.6 },
  { id: "mongo", label: "MongoDB", x: 232, y: 56, color: "var(--color-success)", delay: 1.1 },
  { id: "code", label: "Codebase", x: 232, y: 404, color: "var(--color-warning)", delay: 2.0 },
];

/** Quadratic curve between two points with a perpendicular bend for elegance. */
function curve(
  ax: number,
  ay: number,
  bx: number,
  by: number,
  bend = 22,
): string {
  const mx = (ax + bx) / 2;
  const my = (ay + by) / 2;
  // Perpendicular offset based on the segment direction.
  const dx = bx - ax;
  const dy = by - ay;
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len;
  const ny = dx / len;
  return `M ${ax} ${ay} Q ${mx + nx * bend} ${my + ny * bend} ${bx} ${by}`;
}

export function SchemaGraph({ className = "" }: { className?: string }) {
  const coreToAnswer = curve(CORE.x + 44, CORE.y, ANSWER_IN.x, ANSWER_IN.y, -16);

  return (
    <svg
      viewBox="0 0 720 460"
      role="img"
      aria-hidden="true"
      className={className}
      style={{ display: "block", width: "100%", height: "auto" }}
    >
      <defs>
        <radialGradient id="cmd-core-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.55" />
          <stop offset="60%" stopColor="var(--color-accent)" stopOpacity="0.12" />
          <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="cmd-bar-grad" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0%" stopColor="var(--color-accent-strong)" />
          <stop offset="100%" stopColor="var(--color-accent-hover)" />
        </linearGradient>
      </defs>

      {/* Core ambient glow */}
      <circle cx={CORE.x} cy={CORE.y} r="120" fill="url(#cmd-core-glow)" />

      {/* ── Edges: faint base + bright flowing dashes ── */}
      <g fill="none" strokeLinecap="round">
        {SOURCES.map((n) => {
          const d = curve(n.x, n.y, CORE.x, CORE.y);
          return (
            <g key={`edge-${n.id}`}>
              <path d={d} stroke={n.color} strokeOpacity={0.18} strokeWidth={1.5} />
              <path
                d={d}
                stroke={n.color}
                strokeOpacity={0.9}
                strokeWidth={1.5}
                className="cmd-flow"
                style={
                  {
                    "--cmd-flow-dur": `${3 + n.delay * 0.4}s`,
                  } as CSSProperties
                }
              />
            </g>
          );
        })}

        {/* Core → answer (thicker output stream) */}
        <path d={coreToAnswer} stroke="var(--color-success)" strokeOpacity={0.22} strokeWidth={2} />
        <path
          d={coreToAnswer}
          stroke="var(--color-success)"
          strokeOpacity={0.95}
          strokeWidth={2}
          className="cmd-flow"
          style={{ "--cmd-flow-dur": "2.4s" } as CSSProperties}
        />
      </g>

      {/* ── Traveling query pulses (offset-path along edges) ── */}
      {SOURCES.map((n) => {
        const d = curve(n.x, n.y, CORE.x, CORE.y);
        return (
          <circle
            key={`pulse-${n.id}`}
            r="3.5"
            fill={n.color}
            className="cmd-travel"
            style={
              {
                "--cmd-path": `path('${d}')`,
                "--cmd-travel-dur": `${3.4 + n.delay * 0.3}s`,
                "--cmd-travel-delay": `${n.delay}s`,
              } as CSSProperties
            }
          />
        );
      })}
      <circle
        r="4"
        fill="var(--color-success)"
        className="cmd-travel"
        style={
          {
            "--cmd-path": `path('${coreToAnswer}')`,
            "--cmd-travel-dur": "2.4s",
            "--cmd-travel-delay": "1.2s",
          } as CSSProperties
        }
      />

      {/* ── Source nodes ── */}
      {SOURCES.map((n) => (
        <g key={`node-${n.id}`}>
          <rect
            x={n.x - NODE_W / 2}
            y={n.y - NODE_H / 2}
            width={NODE_W}
            height={NODE_H}
            rx="9"
            fill="var(--color-surface-1)"
            stroke="var(--color-border-default)"
            strokeWidth={1}
          />
          <circle
            cx={n.x - NODE_W / 2 + 18}
            cy={n.y}
            r="4.5"
            fill={n.color}
            className="cmd-node-pulse"
            style={{ "--cmd-node-dur": `${3 + n.delay * 0.5}s` } as CSSProperties}
          />
          <text
            x={n.x - NODE_W / 2 + 32}
            y={n.y + 4}
            fill="var(--color-text-secondary)"
            fontFamily="var(--font-sans)"
            fontSize="12.5"
            fontWeight={500}
          >
            {n.label}
          </text>
        </g>
      ))}

      {/* ── Intelligence core ── */}
      <g>
        {/* Expanding rings */}
        {[0, 1.3, 2.6].map((delay, idx) => (
          <circle
            key={`ring-${idx}`}
            cx={CORE.x}
            cy={CORE.y}
            r="40"
            fill="none"
            stroke="var(--color-accent)"
            strokeWidth={1.25}
            className="cmd-ring"
            style={
              { "--cmd-ring-dur": "4s", "--cmd-ring-delay": `${delay}s` } as CSSProperties
            }
          />
        ))}
        {/* Rotating dashed orbit */}
        <circle
          cx={CORE.x}
          cy={CORE.y}
          r="54"
          fill="none"
          stroke="var(--color-accent)"
          strokeOpacity={0.4}
          strokeWidth={1}
          strokeDasharray="3 8"
          className="cmd-orbit"
        />
        {/* Core disk */}
        <circle
          cx={CORE.x}
          cy={CORE.y}
          r="40"
          fill="var(--color-surface-1)"
          stroke="var(--color-accent)"
          strokeWidth={1.5}
        />
        <circle
          cx={CORE.x}
          cy={CORE.y}
          r="40"
          fill="var(--color-accent)"
          fillOpacity={0.08}
          className="cmd-node-pulse"
          style={{ "--cmd-node-dur": "3.2s" } as CSSProperties}
        />
        {/* Abstract chart mark inside core */}
        <g stroke="var(--color-accent)" strokeWidth={3} strokeLinecap="round">
          <line x1={CORE.x - 12} y1={CORE.y + 10} x2={CORE.x - 12} y2={CORE.y + 2} />
          <line x1={CORE.x} y1={CORE.y + 10} x2={CORE.x} y2={CORE.y - 8} />
          <line x1={CORE.x + 12} y1={CORE.y + 10} x2={CORE.x + 12} y2={CORE.y - 2} />
        </g>
      </g>

      {/* ── Answer card ── */}
      <g>
        <rect
          x="472"
          y="120"
          width="216"
          height="220"
          rx="14"
          fill="var(--color-surface-1)"
          stroke="var(--color-border-default)"
          strokeWidth={1}
        />
        {/* Card header */}
        <circle cx="494" cy="146" r="4" fill="var(--color-success)" />
        <text
          x="506"
          y="150"
          fill="var(--color-text-secondary)"
          fontFamily="var(--font-sans)"
          fontSize="12.5"
          fontWeight={600}
        >
          Verified answer
        </text>
        <line x1="488" y1="166" x2="672" y2="166" stroke="var(--color-border-subtle)" strokeWidth={1} />

        {/* Mini bar chart */}
        {[
          { x: 502, h: 70, c: "url(#cmd-bar-grad)", d: 0 },
          { x: 540, h: 42, c: "var(--color-accent)", d: 0.15 },
          { x: 578, h: 96, c: "url(#cmd-bar-grad)", d: 0.3 },
          { x: 616, h: 58, c: "var(--color-accent-hover)", d: 0.45 },
          { x: 654, h: 110, c: "var(--color-success)", d: 0.6 },
        ].map((bar) => (
          <rect
            key={`bar-${bar.x}`}
            x={bar.x}
            y={300 - bar.h}
            width="22"
            height={bar.h}
            rx="4"
            fill={bar.c}
            className="cmd-bar"
            style={{ "--cmd-bar-delay": `${bar.d}s` } as CSSProperties}
          />
        ))}
        <line x1="488" y1="300" x2="672" y2="300" stroke="var(--color-border-subtle)" strokeWidth={1} />

        {/* Footer insight */}
        <text
          x="488"
          y="324"
          fill="var(--color-success)"
          fontFamily="var(--font-mono)"
          fontSize="11.5"
          fontWeight={600}
        >
          ▲ Revenue +12.4% recovered
        </text>
      </g>
    </svg>
  );
}
