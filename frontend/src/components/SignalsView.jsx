import React from "react";
import { DOMAINS, fmtScore } from "../theme.js";
import { DomainIcon } from "./ui.jsx";

/**
 * "What this detector alone is seeing" — a deliberately simpler, rawer list of a
 * single domain's assessments across all incidents, before correlation fuses them.
 */
export default function SignalsView({ incidents, domainKey }) {
  const d = DOMAINS[domainKey];

  const rows = incidents
    .flatMap((inc) =>
      (inc.contributing_assessments || [])
        .filter((a) => a.reasons?.[0]?.domain === domainKey)
        .map((a) => ({ incident: inc, assessment: a }))
    )
    .sort((x, y) => y.assessment.score - x.assessment.score);

  return (
    <div className="animate-fadein space-y-4">
      <div className={`rounded-xl border ${d.panel} px-5 py-4`}>
        <div className="flex items-center gap-3">
          <span className={`flex h-9 w-9 items-center justify-center rounded-lg bg-white ring-1 ring-black/[0.05] ${d.header}`}>
            <DomainIcon domain={domainKey} className="h-4.5 w-4.5" />
          </span>
          <div>
            <h2 className={`font-display text-lg font-semibold ${d.header}`}>{d.system}</h2>
            <p className="text-xs text-vault-500">
              {d.describes} — raw detector output, <span className="font-medium">before</span> cross-domain correlation.
            </p>
          </div>
        </div>
      </div>

      {rows.length === 0 ? (
        <p className="rounded-xl border border-vault-100 bg-white p-6 text-center text-sm text-vault-500">
          No {d.name.toLowerCase()} signals in the current incident set.
        </p>
      ) : (
        <div className="overflow-hidden rounded-xl border border-vault-100 bg-white shadow-card">
          {rows.map(({ incident, assessment }, i) => (
            <div
              key={`${incident.incident_id}-${i}`}
              className={`flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-4 ${i > 0 ? "border-t border-vault-50" : ""}`}
            >
              <span className={`h-2 w-2 shrink-0 rounded-full ${d.dot}`} />
              <span className="w-14 font-display text-sm font-semibold text-vault-900">
                {incident.entity_id}
              </span>
              <span className="w-16 font-mono text-sm font-semibold text-vault-800">
                {fmtScore(assessment.score)}
              </span>
              <div className="hidden h-1.5 w-28 overflow-hidden rounded-full bg-vault-50 sm:block">
                <div className={`h-full ${d.bar}`} style={{ width: `${Math.round(assessment.score * 100)}%` }} />
              </div>
              <span className="min-w-0 flex-1 truncate text-sm text-vault-600">
                {assessment.reasons?.[0]?.signal_name}
                {assessment.reasons?.length > 1 && (
                  <span className="text-vault-400"> +{assessment.reasons.length - 1} more</span>
                )}
              </span>
              <span className="font-mono text-[11px] text-vault-400">{incident.incident_id}</span>
            </div>
          ))}
        </div>
      )}

      <p className="px-1 text-xs italic leading-relaxed text-vault-400">
        On its own, this detector can&rsquo;t tell a risky-looking anomaly from a real attack.
        Switch to Unified Incidents to see how corroboration across domains separates the two.
      </p>
    </div>
  );
}
