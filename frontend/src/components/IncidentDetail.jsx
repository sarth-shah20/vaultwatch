import React, { useState } from "react";
import {
  CORRELATION_WINDOW_MIN,
  DOMAIN,
  assessmentsByDomain,
  convergenceGapMinutes,
  decisionOf,
  domainOf,
  fmtClock,
  fmtDateTime,
  fmtGap,
  fmtScore,
  isCorroborated,
  parseTime,
  shortEntity,
} from "../lib/model.js";
import { sendFeedback } from "../lib/api.js";
import { CorroborationMark, DecisionChip, DomainTag, Eyebrow } from "./primitives.jsx";

/** The 120-minute window, drawn to scale — where corroboration is won or lost. */
function MicroWindow({ incident }) {
  const by = assessmentsByDomain(incident);
  const ps1 = by.ps1_behavioral;
  const ps2 = by.ps2_transaction;
  const signals = [ps1, ps2].filter(Boolean).filter((a) => a.event_time);
  if (!signals.length) return null;

  const times = signals.map((a) => parseTime(a.event_time)).sort((a, b) => a - b);
  const start = times[0];
  const gapMin = convergenceGapMinutes(incident);
  const windowMs = CORRELATION_WINDOW_MIN * 60000;

  const W = 900, H = 148, L = 20, R = 20, Y = 66;
  const trackW = W - L - R;
  const pos = (d) => L + Math.min(1, (d - start) / windowMs) * trackW;
  // Keep a marker's caption inside the canvas when it sits on an edge.
  const anchorFor = (x) => (x < L + 34 ? "start" : x > W - R - 34 ? "end" : "middle");
  const labelX = (x) => (x < L + 34 ? L : x > W - R - 34 ? W - R : x);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block w-full">
      {/* the window itself */}
      <rect x={L} y={Y - 17} width={trackW} height="34" rx="2"
            fill="#101820" stroke="#1E2833" strokeWidth="1" />
      <line x1={L} y1={Y} x2={W - R} y2={Y} stroke="#26313E" strokeWidth="1" />

      {/* window bounds */}
      <line x1={L} y1={Y - 21} x2={L} y2={Y + 21} stroke="#3A4757" strokeWidth="1" />
      <line x1={W - R} y1={Y - 21} x2={W - R} y2={Y + 21} stroke="#3A4757" strokeWidth="1" />
      {/* Window bounds sit on their own baseline, clear of the marker captions. */}
      <text x={L} y={Y + 58} className="font-mono" fontSize="11" fill="#5D6B7D" letterSpacing="0.08em">
        {fmtClock(start)}Z
      </text>
      <text x={W - R} y={Y + 58} textAnchor="end" className="font-mono" fontSize="11" fill="#5D6B7D" letterSpacing="0.08em">
        +{CORRELATION_WINDOW_MIN} MIN
      </text>

      {/* the measured gap between the two domains */}
      {ps1 && ps2 && gapMin != null && (() => {
        const a = pos(parseTime(ps1.event_time));
        const b = pos(parseTime(ps2.event_time));
        const [x1, x2] = a < b ? [a, b] : [b, a];
        return (
          <g>
            <rect x={x1} y={Y - 17} width={Math.max(1, x2 - x1)} height="34" fill="#E5484D" opacity="0.09" />
            <line x1={x1} y1={Y - 26} x2={x2} y2={Y - 26} stroke="#E5484D" strokeWidth="1" opacity="0.55" />
            <text x={(x1 + x2) / 2} y={Y - 32} textAnchor="middle" className="font-mono"
                  fontSize="12" fill="#F27579" letterSpacing="0.06em">
              {fmtGap(gapMin)} apart
            </text>
          </g>
        );
      })()}

      {/* signal markers */}
      {ps1 && ps1.event_time && (
        <g>
          <line x1={pos(parseTime(ps1.event_time))} y1={Y - 17} x2={pos(parseTime(ps1.event_time))} y2={Y}
                stroke={DOMAIN.ps1_behavioral.hex} strokeWidth="1.5" />
          <circle cx={pos(parseTime(ps1.event_time))} cy={Y - 17} r="4.5"
                  className="animate-landing" style={{ transformOrigin: `${pos(parseTime(ps1.event_time))}px ${Y - 17}px` }}
                  fill={DOMAIN.ps1_behavioral.hex} stroke="#0B0F14" strokeWidth="1.25" />
          <text x={labelX(pos(parseTime(ps1.event_time)))} y={Y - 46}
                textAnchor={anchorFor(pos(parseTime(ps1.event_time)))}
                className="font-mono" fontSize="11" fill={DOMAIN.ps1_behavioral.hex} letterSpacing="0.06em">
            PS1 {fmtScore(ps1.score)} · {fmtClock(parseTime(ps1.event_time))}Z
          </text>
        </g>
      )}
      {ps2 && ps2.event_time && (
        <g>
          <line x1={pos(parseTime(ps2.event_time))} y1={Y} x2={pos(parseTime(ps2.event_time))} y2={Y + 17}
                stroke={DOMAIN.ps2_transaction.hex} strokeWidth="1.5" />
          <circle cx={pos(parseTime(ps2.event_time))} cy={Y + 17} r="4.5"
                  className="animate-landing" style={{ transformOrigin: `${pos(parseTime(ps2.event_time))}px ${Y + 17}px`, animationDelay: "120ms" }}
                  fill={DOMAIN.ps2_transaction.hex} stroke="#0B0F14" strokeWidth="1.25" />
          <text x={labelX(pos(parseTime(ps2.event_time)))} y={Y + 38}
                textAnchor={anchorFor(pos(parseTime(ps2.event_time)))}
                className="font-mono" fontSize="11" fill={DOMAIN.ps2_transaction.hex} letterSpacing="0.06em">
            PS2 {fmtScore(ps2.score)} · {fmtClock(parseTime(ps2.event_time))}Z
          </text>
        </g>
      )}
    </svg>
  );
}

function EvidenceColumn({ domain, assessment }) {
  const d = domainOf(domain);
  if (!assessment) {
    return (
      <div className="rounded border border-dashed border-ink-700 p-4">
        <DomainTag domain={domain} />
        <p className="mt-3 text-[14.5px] leading-relaxed text-chalk-faint">
          No {d.label.toLowerCase()} signal fired for this entity inside the window.
          <span className="mt-2 block text-chalk-faint/80">
            The absence is the reason this stayed uncorroborated — and why the
            engine held back from a revoke.
          </span>
        </p>
      </div>
    );
  }
  return (
    <div className="rounded border p-4" style={{ borderColor: `${d.hex}2e`, background: `${d.hex}09` }}>
      <div className="flex items-center justify-between">
        <DomainTag domain={domain} />
        <span className="tnum font-mono text-[17px]" style={{ color: d.hex }}>{fmtScore(assessment.score)}</span>
      </div>

      <div className="mt-3 space-y-2.5">
        {(assessment.reasons || []).map((r, i) => (
          <div key={i}>
            <div className="flex items-baseline justify-between gap-3">
              <span className="font-mono text-[13.5px] text-chalk">{r.signal_name}</span>
              <span className="tnum font-mono text-micro text-chalk-faint">{(r.weight * 100).toFixed(0)}%</span>
            </div>
            <div className="mt-1 h-[2px] w-full overflow-hidden bg-ink-700">
              <div className="h-full" style={{ width: `${Math.max(2, r.weight * 100)}%`, background: d.hex }} />
            </div>
            <p className="mt-1 text-[13.5px] leading-snug text-chalk-dim">{r.raw_value}</p>
          </div>
        ))}
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-1.5 border-t rule pt-3 font-mono text-micro">
        <dt className="text-chalk-faint">EVENT</dt>
        <dd className="text-right text-chalk-dim">{fmtDateTime(parseTime(assessment.event_time))}</dd>
        <dt className="text-chalk-faint">SOURCE</dt>
        <dd className="truncate text-right text-chalk-dim" title={assessment.source}>{assessment.source}</dd>
        <dt className="text-chalk-faint">MODEL</dt>
        <dd className="truncate text-right text-chalk-dim" title={assessment.model_version}>{assessment.model_version}</dd>
        <dt className="text-chalk-faint">BASIS</dt>
        <dd className="truncate text-right text-chalk-dim" title={assessment.time_basis}>{assessment.time_basis}</dd>
      </dl>
    </div>
  );
}

/** Shows the actual gate: revoke needs a high score AND corroboration. */
function DecisionLadder({ incident }) {
  const corroborated = isCorroborated(incident);
  const score = incident.combined_score;
  const active = incident.access_decision;

  const rungs = [
    { k: "revoke", ok: score >= 0.9 && corroborated, note: "score ≥ ·900 + corroborated" },
    { k: "step_up_auth", ok: score >= 0.7, note: "score ≥ ·700" },
    { k: "throttle", ok: score >= 0.4, note: "score ≥ ·400" },
    { k: "allow", ok: true, note: "below thresholds" },
  ];

  return (
    <div>
      <Eyebrow>Decision gate</Eyebrow>
      <div className="mt-2.5 space-y-1">
        {rungs.map((r) => {
          const d = decisionOf(r.k);
          const on = r.k === active;
          return (
            <div key={r.k}
                 className={`flex items-center gap-3 rounded-sm border px-2.5 py-1.5 transition-colors ${
                   on ? "border-transparent" : "border-transparent opacity-45"}`}
                 style={on ? { background: `${d.hex}14`, borderColor: `${d.hex}40` } : undefined}>
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: on ? d.hex : "#2A3644" }} />
              <span className="font-mono text-tiny uppercase tracking-[0.1em]" style={{ color: on ? d.hex : "#5D6B7D" }}>
                {d.short}
              </span>
              <span className="ml-auto font-mono text-micro text-chalk-faint">{r.note}</span>
            </div>
          );
        })}
      </div>
      {!corroborated && (
        <p className="mt-3 border-l-2 border-ps1/40 pl-3 text-[14px] leading-relaxed text-chalk-dim">
          A lone signal is capped at step-up verification no matter how loud it is.
          <span className="text-chalk-faint"> That cap is the false-positive defence — nobody is locked out on one detector’s word.</span>
        </p>
      )}
    </div>
  );
}

const ACTIONS = [
  { key: "acknowledge", label: "Acknowledge" },
  { key: "escalate", label: "Escalate" },
  { key: "dismiss", label: "Dismiss" },
];

export default function IncidentDetail({ incident, onUpdated, onClose }) {
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const by = assessmentsByDomain(incident);
  const d = decisionOf(incident.access_decision);
  const gap = convergenceGapMinutes(incident);

  async function act(action) {
    setBusy(action);
    setErr(null);
    try {
      onUpdated(await sendFeedback(incident.incident_id, action));
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="animate-riseIn">
      {/* header */}
      <div className="flex flex-wrap items-start justify-between gap-4 border-b rule pb-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <h3 className="font-mono text-[21px] font-semibold tracking-tight text-chalk">
              {shortEntity(incident.entity_id)}
            </h3>
            <DecisionChip decision={incident.access_decision} size="lg" />
            {incident.suppressed && (
              <span className="rounded-sm border border-ink-600 px-2 py-0.5 font-mono text-micro uppercase tracking-wider text-chalk-faint">
                suppressed
              </span>
            )}
          </div>
          <p className="mt-1.5 font-mono text-micro text-chalk-faint">{incident.incident_id}</p>
        </div>

        <div className="flex items-center gap-6">
          <div className="text-right">
            <Eyebrow>Combined</Eyebrow>
            <div className="tnum mt-0.5 font-mono text-[28px] leading-none" style={{ color: d.hex }}>
              {fmtScore(incident.combined_score)}
            </div>
          </div>
          <div className="text-right">
            <Eyebrow>Status</Eyebrow>
            <div className="mt-1 font-mono text-tiny uppercase tracking-wider text-chalk">{incident.status}</div>
            <div className="mt-1.5">
              <CorroborationMark level={incident.confidence} domains={incident.contributing_domains} />
            </div>
          </div>
          {onClose && (
            <button onClick={onClose} className="focusable rounded border border-ink-700 px-2 py-1 text-tiny text-chalk-dim hover:border-ink-500 hover:text-chalk">
              Close
            </button>
          )}
        </div>
      </div>

      {/* micro window */}
      <div className="mt-5">
        <div className="flex items-baseline justify-between">
          <Eyebrow>Correlation window · {CORRELATION_WINDOW_MIN} min</Eyebrow>
          {gap != null && (
            <span className="font-mono text-micro text-chalk-faint">
              signals {fmtGap(gap)} apart — inside window
            </span>
          )}
        </div>
        <div className="mt-1">
          <MicroWindow incident={incident} />
        </div>
      </div>

      {/* evidence */}
      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <EvidenceColumn domain="ps1_behavioral" assessment={by.ps1_behavioral} />
        <EvidenceColumn domain="ps2_transaction" assessment={by.ps2_transaction} />
      </div>

      {/* gate + analyst actions */}
      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_260px]">
        <DecisionLadder incident={incident} />
        <div>
          <Eyebrow>Analyst</Eyebrow>
          <div className="mt-2.5 flex flex-col gap-1.5">
            {ACTIONS.map((a) => (
              <button key={a.key} disabled={!!busy} onClick={() => act(a.key)}
                      className="focusable flex items-center justify-between rounded-sm border border-ink-700 px-3 py-2 text-left text-[14.5px] text-chalk-dim transition-colors hover:border-ink-500 hover:bg-ink-800 hover:text-chalk disabled:opacity-40">
                <span>{a.label}</span>
                <span className="font-mono text-micro text-chalk-faint">{busy === a.key ? "···" : "→"}</span>
              </button>
            ))}
          </div>
          {err && <p className="mt-2 font-mono text-micro text-alert-soft">{err}</p>}
          <p className="mt-3 text-[13.5px] leading-relaxed text-chalk-faint">
            Dismissing suppresses future lone alerts for this entity.
          </p>
        </div>
      </div>
    </div>
  );
}
