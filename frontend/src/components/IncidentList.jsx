import React from "react";
import { DECISIONS, DOMAINS, STATUS_LABELS, fmtTime } from "../theme.js";
import {
  ConfidenceBadge,
  CorroborationMark,
  DecisionBadge,
  DecisionLegend,
  DomainChip,
  ScoreGauge,
} from "./ui.jsx";

function topSignal(incident) {
  const reasons = (incident.contributing_assessments || []).flatMap((a) => a.reasons || []);
  if (!reasons.length) return null;
  return reasons.reduce((best, r) => (r.weight > (best?.weight ?? -1) ? r : best), null);
}

function IncidentCard({ incident, onOpen, index }) {
  const d = DECISIONS[incident.access_decision] || DECISIONS.allow;
  const both = (incident.contributing_domains || []).length >= 2;
  const signal = topSignal(incident);
  return (
    <button
      onClick={() => onOpen(incident)}
      className={`group w-full animate-rise rounded-2xl border border-vault-100 border-l-4 ${d.edge} bg-white p-5 text-left shadow-card transition-all duration-200 hover:-translate-y-0.5 hover:border-vault-200 hover:shadow-lift focus:outline-none focus-visible:ring-2 focus-visible:ring-vault-500`}
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <div className="flex items-center gap-5">
        <ScoreGauge score={incident.combined_score} decision={incident.access_decision} />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-display text-lg font-semibold text-vault-900">
              {incident.entity_id}
            </span>
            <span className="font-mono text-xs text-vault-500">{incident.incident_id}</span>
            <ConfidenceBadge confidence={incident.confidence} />
            {incident.suppressed && (
              <span className="rounded-md bg-vault-50 px-2 py-0.5 text-[11px] font-medium text-vault-500">
                Suppressed
              </span>
            )}
          </div>

          {signal && (
            <p className="mt-1.5 truncate text-sm text-vault-600">
              {signal.signal_name}
              <span className="text-vault-400"> · {STATUS_LABELS[incident.status] || incident.status}</span>
              <span className="text-vault-400"> · {fmtTime(incident.created_at)}</span>
            </p>
          )}

          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            {(incident.contributing_domains || []).map((dom) => (
              <DomainChip key={dom} domain={dom} />
            ))}
            {both ? (
              <CorroborationMark />
            ) : (
              <span className="text-[11px] italic text-vault-400">
                no corroborating {incident.contributing_domains?.[0] === "ps1_behavioral" ? "transaction" : "behavioral"} signal
              </span>
            )}
          </div>
        </div>

        <div className="flex flex-col items-end gap-2">
          <DecisionBadge decision={incident.access_decision} />
          <span className="text-xs text-vault-300 transition-transform duration-200 group-hover:translate-x-0.5">
            View evidence →
          </span>
        </div>
      </div>
    </button>
  );
}

function StatCell({ value, label, sub, tone = "text-vault-950", divider }) {
  return (
    <div className={`flex-1 px-5 py-4 ${divider ? "border-l border-vault-50" : ""}`}>
      <p className={`font-display text-[26px] font-semibold leading-none tabular-nums ${tone}`}>{value}</p>
      <p className="mt-1.5 text-xs font-semibold text-vault-700">{label}</p>
      <p className="mt-0.5 text-[11px] text-vault-400">{sub}</p>
    </div>
  );
}

export default function IncidentList({ incidents, onOpen }) {
  const sorted = [...incidents].sort((a, b) => b.combined_score - a.combined_score);
  const corroborated = sorted.filter((i) => (i.contributing_domains || []).length >= 2).length;
  const lone = sorted.length - corroborated;
  const revokes = sorted.filter((i) => i.access_decision === "revoke").length;
  return (
    <div className="space-y-4">
      {/* posture at a glance */}
      <div className="flex animate-rise overflow-hidden rounded-2xl border border-vault-100 bg-white shadow-card">
        <StatCell value={sorted.length} label="Open incidents" sub="Across both signal domains" />
        <StatCell
          value={corroborated}
          label="Corroborated"
          sub="Both domains agree — high confidence"
          tone="text-[#5c1a24]"
          divider
        />
        <StatCell
          value={lone}
          label="Single-domain"
          sub="Held at low confidence — verify, don't lock out"
          tone="text-[#8a5a13]"
          divider
        />
        <StatCell value={revokes} label="Access revoked" sub="Strongest response, earned by evidence" divider />
      </div>

      <DecisionLegend />

      <div className="flex items-baseline justify-between px-1">
        <h2 className="font-display text-xl font-semibold text-vault-900">Unified incidents</h2>
        <p className="text-xs text-vault-500">sorted by combined risk</p>
      </div>

      <div className="space-y-3">
        {sorted.map((incident, i) => (
          <IncidentCard key={incident.incident_id} incident={incident} onOpen={onOpen} index={i} />
        ))}
      </div>
    </div>
  );
}
