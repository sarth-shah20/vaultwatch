import React, { useState } from "react";
import { sendFeedback } from "../api.js";
import { CONFIDENCE, DECISIONS, DOMAINS, STATUS_LABELS, fmtScore, fmtTime } from "../theme.js";
import { ConfidenceBadge, CorroborationMark, DecisionBadge, DomainIcon, ScoreGauge } from "./ui.jsx";

/* ---------- one weighted reason row ---------- */
function ReasonRow({ reason, barClass }) {
  const pct = Math.round(Math.min(1, Math.max(0, reason.weight)) * 100);
  return (
    <li className="rounded-lg bg-white/80 p-3 ring-1 ring-black/[0.04]">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-semibold text-vault-800">{reason.signal_name}</span>
        <span className="shrink-0 font-mono text-xs text-vault-500">w {fmtScore(reason.weight)}</span>
      </div>
      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-black/[0.05]">
        <div
          className={`h-full rounded-full ${barClass} transition-[width] duration-700 ease-out`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-2 text-xs leading-relaxed text-vault-600">{reason.raw_value}</p>
    </li>
  );
}

/* ---------- an evidence panel for one domain (or its absence) ---------- */
function EvidencePanel({ domainKey, assessment }) {
  const d = DOMAINS[domainKey];

  if (!assessment) {
    const otherName = d.name.toLowerCase();
    return (
      <div className="flex min-h-[220px] flex-col items-center justify-center rounded-2xl border-2 border-dashed border-vault-200 bg-white/40 p-6 text-center">
        <DomainIcon domain={domainKey} className="h-6 w-6 text-vault-300" />
        <p className="mt-3 text-sm font-semibold text-vault-500">
          No corroborating {otherName} signal
        </p>
        <p className="mt-1.5 max-w-[26ch] text-xs leading-relaxed text-vault-400">
          {d.system} saw nothing for this entity — so confidence stays{" "}
          <span className="font-semibold">low</span> and the response stays measured.
        </p>
      </div>
    );
  }

  return (
    <div className={`animate-rise rounded-2xl border ${d.panel} p-5`}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className={`flex h-8 w-8 items-center justify-center rounded-lg bg-white ring-1 ring-black/[0.05] ${d.header}`}>
            <DomainIcon domain={domainKey} className="h-4 w-4" />
          </span>
          <div>
            <p className={`text-sm font-bold ${d.header}`}>{d.name} evidence</p>
            <p className="text-[11px] text-vault-500">{d.system}</p>
          </div>
        </div>
        <div className="text-right">
          <p className={`font-mono text-lg font-semibold ${d.header}`}>{fmtScore(assessment.score)}</p>
          <p className="text-[10px] uppercase tracking-wider text-vault-400">domain score</p>
        </div>
      </div>
      <ul className="mt-4 space-y-2.5">
        {(assessment.reasons || []).map((r, i) => (
          <ReasonRow key={i} reason={r} barClass={d.bar} />
        ))}
      </ul>
    </div>
  );
}

/* ---------- feedback actions ---------- */
const ACTIONS = [
  { action: "acknowledge", label: "Acknowledge", style: "border border-vault-200 bg-white text-vault-800 hover:bg-vault-50" },
  { action: "escalate", label: "Escalate", style: "bg-vault-900 text-white hover:bg-vault-800" },
  { action: "dismiss", label: "Dismiss", style: "border border-vault-200 bg-white text-vault-500 hover:bg-vault-50" },
];

function FeedbackBar({ incident, onUpdated }) {
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState(null);

  const act = async (action) => {
    setBusy(action);
    setNotice(null);
    try {
      const updated = await sendFeedback(incident.incident_id, action, `analyst ${action} via dashboard`);
      onUpdated(updated);
      setNotice({
        tone: "ok",
        text:
          action === "dismiss"
            ? `Dismissed — future lone alerts for ${incident.entity_id} are suppressed.`
            : `Marked as ${STATUS_LABELS[updated.status]?.toLowerCase() || updated.status}.`,
      });
    } catch (e) {
      setNotice({
        tone: "warn",
        text:
          e.status === 409
            ? `That transition isn't allowed from the current "${STATUS_LABELS[incident.status] || incident.status}" state.`
            : "Couldn't record feedback — the API didn't respond. Try again.",
      });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2.5">
        <span className="mr-1 text-xs font-semibold uppercase tracking-[0.12em] text-vault-400">
          Analyst response
        </span>
        {ACTIONS.map((a) => (
          <button
            key={a.action}
            disabled={busy !== null}
            onClick={() => act(a.action)}
            className={`rounded-lg px-4 py-2 text-sm font-semibold transition active:scale-[0.98] disabled:opacity-50 ${a.style}`}
          >
            {busy === a.action ? "Saving…" : a.label}
          </button>
        ))}
      </div>
      {notice && (
        <p
          className={`mt-2.5 animate-fadein rounded-lg px-3 py-2 text-xs font-medium ${
            notice.tone === "ok" ? "bg-vault-50 text-vault-700" : "bg-[#fbf4e6] text-[#7a4f10]"
          }`}
        >
          {notice.text}
        </p>
      )}
    </div>
  );
}

/* ---------- the full detail view ---------- */
export default function IncidentDetail({ incident, onBack, onUpdated }) {
  const byDomain = {};
  for (const a of incident.contributing_assessments || []) {
    const dom = a.reasons?.[0]?.domain;
    if (dom && (!byDomain[dom] || a.score > byDomain[dom].score)) byDomain[dom] = a;
  }
  const both = (incident.contributing_domains || []).length >= 2;
  const conf = CONFIDENCE[incident.confidence] || CONFIDENCE.low;

  return (
    <div className="animate-fadein space-y-5">
      <button
        onClick={onBack}
        className="group inline-flex items-center gap-1.5 text-sm font-medium text-vault-500 transition hover:text-vault-900"
      >
        <span className="transition-transform duration-200 group-hover:-translate-x-0.5">←</span>
        All incidents
      </button>

      {/* verdict banner */}
      <div className="animate-rise rounded-2xl border border-vault-100 bg-white p-6 shadow-card">
        <div className="flex flex-wrap items-center gap-6">
          <ScoreGauge score={incident.combined_score} decision={incident.access_decision} size={88} stroke={6} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2.5">
              <h2 className="font-display text-2xl font-semibold text-vault-900">
                {incident.entity_id}
              </h2>
              <span className="font-mono text-xs text-vault-400">{incident.incident_id}</span>
            </div>
            <p className="mt-1 text-sm text-vault-500">
              {STATUS_LABELS[incident.status] || incident.status} · opened {fmtTime(incident.created_at)}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <DecisionBadge decision={incident.access_decision} size="lg" />
              <ConfidenceBadge confidence={incident.confidence} />
              {both && <CorroborationMark />}
            </div>
          </div>
          <p className="max-w-[30ch] border-l border-vault-100 pl-5 text-xs leading-relaxed text-vault-500">
            {both
              ? "Independent behavioral and transaction signals agree for this entity — corroboration raised confidence to high and unlocked the strongest response."
              : `${conf.note}. A single domain never triggers a revoke on its own — the system asks for verification instead of locking out.`}
          </p>
        </div>

        <div className="mt-5 border-t border-vault-50 pt-4">
          <FeedbackBar incident={incident} onUpdated={onUpdated} />
        </div>
      </div>

      {/* evidence: PS1 vs PS2, absence rendered explicitly */}
      <div className="grid gap-4 lg:grid-cols-2">
        <EvidencePanel domainKey="ps1_behavioral" assessment={byDomain.ps1_behavioral} />
        <EvidencePanel domainKey="ps2_transaction" assessment={byDomain.ps2_transaction} />
      </div>
    </div>
  );
}
