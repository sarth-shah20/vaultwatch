import React, { useMemo } from "react";
import {
  DOMAIN,
  decisionOf,
  fmtDate,
  incidentTime,
  isCorroborated,
  assessmentsByDomain,
  shortEntity,
} from "../lib/model.js";

// Logical canvas. Rendered responsively via viewBox; on narrow screens the
// wrapper scrolls rather than squashing the axis.
const W = 1240;
const H = 260;
const PAD_L = 150; // room for the lane captions
const PAD_R = 24;
const AXIS_Y = H / 2;
const LANE = 74;

const DAY = 86400000;

function niceTicks(min, max, target = 7) {
  const span = max - min;
  const steps = [DAY, 2 * DAY, 3 * DAY, 7 * DAY, 14 * DAY, 28 * DAY];
  const step = steps.find((s) => span / s <= target) || 90 * DAY;
  const first = new Date(min);
  first.setUTCHours(0, 0, 0, 0);
  const out = [];
  for (let t = first.getTime(); t <= max + step; t += step) if (t >= min) out.push(t);
  return out;
}

/**
 * The product thesis, drawn: two domains on opposite lanes, and a signal only
 * "locks" onto the decision axis when both fired for one entity inside the
 * correlation window. A lone signal keeps its lane, stays hollow, never lands.
 */
export default function ConvergenceTimeline({ incidents, selectedId, onSelect, recentIds }) {
  const model = useMemo(() => {
    const timed = [];
    const untimed = [];
    for (const inc of incidents) {
      const t = incidentTime(inc);
      (t ? timed : untimed).push({ inc, t });
    }
    timed.sort((a, b) => a.t - b.t);
    if (!timed.length) return { nodes: [], ticks: [], untimed };

    const min = timed[0].t.getTime();
    const max = timed[timed.length - 1].t.getTime();
    const span = Math.max(max - min, 3600000);
    const lo = min - span * 0.03;
    const hi = max + span * 0.03;
    const x = (t) => PAD_L + ((t - lo) / (hi - lo)) * (W - PAD_L - PAD_R);

    const nodes = timed.map(({ inc, t }) => {
      const by = assessmentsByDomain(inc);
      return {
        inc,
        id: inc.incident_id,
        x: x(t.getTime()),
        t,
        ps1: by.ps1_behavioral || null,
        ps2: by.ps2_transaction || null,
        corroborated: isCorroborated(inc),
        decision: decisionOf(inc.access_decision),
      };
    });

    // Push apart nodes that would otherwise sit on top of each other, then
    // re-centre so the nudging can't drift the whole run off the canvas.
    const MIN_GAP = 17;
    for (let i = 1; i < nodes.length; i++) {
      if (nodes[i].x - nodes[i - 1].x < MIN_GAP) nodes[i].x = nodes[i - 1].x + MIN_GAP;
    }
    const overflow = nodes[nodes.length - 1].x - (W - PAD_R);
    if (overflow > 0) {
      const shift = Math.min(overflow, nodes[0].x - PAD_L);
      nodes.forEach((n) => (n.x -= shift));
      const still = nodes[nodes.length - 1].x - (W - PAD_R);
      if (still > 0) {
        const scale = (W - PAD_R - PAD_L) / (nodes[nodes.length - 1].x - nodes[0].x);
        const base = nodes[0].x;
        nodes.forEach((n) => (n.x = PAD_L + (n.x - base) * scale));
      }
    }

    // A label is only drawn where there is genuinely room for it.
    const LABEL_W = 60;
    nodes.forEach((n, i) => {
      const prev = nodes[i - 1];
      const next = nodes[i + 1];
      n.roomy =
        (!prev || n.x - prev.x >= LABEL_W) && (!next || next.x - n.x >= LABEL_W);
    });

    return { nodes, ticks: niceTicks(lo, hi), x, lo, hi, untimed };
  }, [incidents]);

  const { nodes, ticks, x, untimed } = model;
  if (!nodes.length) return null;

  // Drop tick labels that would collide with the previous one.
  let lastLabelX = -Infinity;

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full min-w-[820px]" role="img"
           aria-label="Convergence timeline of behavioural and transaction signals">
        <defs>
          {/* userSpaceOnUse is required: a vertical line has a zero-width
              bounding box, so the default objectBoundingBox units would
              collapse this gradient and the stem would not paint at all. */}
          <linearGradient id="convStem" gradientUnits="userSpaceOnUse"
                          x1="0" y1={AXIS_Y - LANE} x2="0" y2={AXIS_Y + LANE}>
            <stop offset="0%" stopColor={DOMAIN.ps1_behavioral.hex} stopOpacity="0.95" />
            <stop offset="48%" stopColor="#E5484D" stopOpacity="1" />
            <stop offset="52%" stopColor="#E5484D" stopOpacity="1" />
            <stop offset="100%" stopColor={DOMAIN.ps2_transaction.hex} stopOpacity="0.95" />
          </linearGradient>
          <filter id="glow" x="-120%" y="-120%" width="340%" height="340%">
            <feGaussianBlur stdDeviation="3.5" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* lane guides */}
        {[AXIS_Y - LANE, AXIS_Y + LANE].map((y, i) => (
          <line key={i} x1={PAD_L} y1={y} x2={W - PAD_R} y2={y}
                stroke="#1A222C" strokeWidth="1" strokeDasharray="2 6"
                className="origin-left animate-growX" style={{ animationDelay: "60ms" }} />
        ))}

        {/* date ticks */}
        {ticks.map((t) => {
          const tx = x(t);
          if (tx < PAD_L - 1 || tx > W - PAD_R + 1) return null;
          const showLabel = tx - lastLabelX > 64;
          if (showLabel) lastLabelX = tx;
          return (
            <g key={t}>
              <line x1={tx} y1={AXIS_Y - LANE - 18} x2={tx} y2={AXIS_Y + LANE + 18}
                    stroke="#141B24" strokeWidth="1" />
              {showLabel && (
                <text x={tx} y={AXIS_Y + LANE + 36} textAnchor="middle"
                      className="font-mono" fontSize="11.5" fill="#4B5768" letterSpacing="0.1em">
                  {fmtDate(new Date(t)).toUpperCase()}
                </text>
              )}
            </g>
          );
        })}

        {/* the decision axis */}
        <line x1={PAD_L} y1={AXIS_Y} x2={W - PAD_R} y2={AXIS_Y} stroke="#2A3644" strokeWidth="1"
              className="origin-left animate-growX" />

        {/* lane captions */}
        <text x={0} y={AXIS_Y - LANE + 4} className="font-mono" fontSize="11.5"
              fill={DOMAIN.ps1_behavioral.hex} letterSpacing="0.13em">PS1 · BEHAVIOURAL</text>
        <text x={0} y={AXIS_Y + LANE + 4} className="font-mono" fontSize="11.5"
              fill={DOMAIN.ps2_transaction.hex} letterSpacing="0.13em">PS2 · TRANSACTION</text>
        <text x={0} y={AXIS_Y + 3.5} className="font-mono" fontSize="11.5"
              fill="#5D6B7D" letterSpacing="0.13em">DECISION</text>

        {nodes.map((n, i) => {
          const sel = n.id === selectedId;
          const fresh = recentIds?.has(n.id);
          const y1 = AXIS_Y - LANE;
          const y2 = AXIS_Y + LANE;
          const dim = selectedId && !sel ? 0.28 : 1;

          const delay = `${Math.min(i, 24) * 22}ms`;

          return (
            <g key={n.id} opacity={dim} className="cursor-pointer transition-opacity"
               onClick={() => onSelect(sel ? null : n.id)}>
              <title>{`${shortEntity(n.inc.entity_id)} · ${n.decision.short}`}</title>
              <rect x={n.x - 10} y={y1 - 20} width="20" height={LANE * 2 + 40} fill="transparent" />

              {/* Entrance is isolated to this inner group: its fill-mode locks
                  opacity to 1 once played, which would otherwise permanently
                  override the outer group's selection-dim attribute above. */}
              <g className="animate-riseIn" style={{ animationDelay: delay }}>
                {n.corroborated ? (
                  <>
                    <line x1={n.x} y1={y1} x2={n.x} y2={y2} stroke="url(#convStem)"
                          strokeWidth={sel ? 2 : 1.25} opacity={sel ? 1 : 0.7}
                          className="animate-growY" style={{ animationDelay: delay }} />
                    <g style={{ transformOrigin: `${n.x}px ${AXIS_Y}px` }}
                       className={fresh ? "animate-landing" : undefined}>
                      <rect x={n.x - 5} y={AXIS_Y - 5} width="10" height="10"
                            transform={`rotate(45 ${n.x} ${AXIS_Y})`}
                            fill={n.decision.hex} stroke="#0B0F14" strokeWidth="1.5"
                            filter={sel || fresh ? "url(#glow)" : undefined} />
                    </g>
                  </>
                ) : (
                  <>
                    <line x1={n.x} y1={n.ps1 ? y1 : y2} x2={n.x} y2={n.ps1 ? AXIS_Y - 14 : AXIS_Y + 14}
                          stroke={n.ps1 ? DOMAIN.ps1_behavioral.hex : DOMAIN.ps2_transaction.hex}
                          strokeWidth="1" strokeDasharray="2 4" opacity="0.45" />
                    <circle cx={n.x} cy={AXIS_Y} r="4" fill="#0B0F14" stroke="#3A4757" strokeWidth="1.25" />
                  </>
                )}

                {n.ps1 && (
                  <circle cx={n.x} cy={y1} r={sel ? 5 : 3.4} fill={DOMAIN.ps1_behavioral.hex}
                          stroke="#0B0F14" strokeWidth="1.25" filter={sel ? "url(#glow)" : undefined} />
                )}
                {n.ps2 && (
                  <circle cx={n.x} cy={y2} r={sel ? 5 : 3.4} fill={DOMAIN.ps2_transaction.hex}
                          stroke="#0B0F14" strokeWidth="1.25" filter={sel ? "url(#glow)" : undefined} />
                )}

                {(sel || n.roomy) && (
                  <text x={n.x} y={y1 - 13} textAnchor="middle" className="font-mono"
                        fontSize="11" letterSpacing="0.05em" fill={sel ? "#E7ECF3" : "#55637333"}
                        style={{ fill: sel ? "#E7ECF3" : "#556373" }}>
                    {shortEntity(n.inc.entity_id)}
                  </text>
                )}
              </g>
            </g>
          );
        })}
      </svg>

      {/* Signals with no event time can't sit on a time axis — and per the
          engine they can never corroborate. Shown, but off the axis. */}
      {untimed.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-dashed border-ink-700 pt-3">
          <span className="eyebrow">Off-axis · no event time</span>
          {untimed.map(({ inc }) => {
            const d = decisionOf(inc.access_decision);
            const sel = inc.incident_id === selectedId;
            return (
              <button
                key={inc.incident_id}
                onClick={() => onSelect(sel ? null : inc.incident_id)}
                className={`focusable inline-flex items-center gap-2 rounded-sm border px-2 py-1 font-mono text-micro transition-colors ${
                  sel ? "bg-ink-800" : "hover:bg-ink-850"
                }`}
                style={{ borderColor: `${d.hex}40`, color: d.hex }}
              >
                <span className="h-2 w-2 rounded-full border" style={{ borderColor: d.hex }} />
                {shortEntity(inc.entity_id)} · {d.short}
              </button>
            );
          })}
          <span className="text-[13px] text-chalk-faint">
            no timestamp → cannot enter a correlation window
          </span>
        </div>
      )}
    </div>
  );
}
