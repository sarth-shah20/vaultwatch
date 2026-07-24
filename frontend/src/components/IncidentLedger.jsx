import React from "react";
import {
  assessmentsByDomain,
  convergenceGapMinutes,
  decisionOf,
  fmtDateTime,
  fmtGap,
  fmtScore,
  incidentTime,
  isCorroborated,
  shortEntity,
} from "../lib/model.js";
import { CorroborationMark, DecisionChip, Empty } from "./primitives.jsx";

/**
 * Dense tabular ledger. Deliberately a table, not cards: analysts scan columns,
 * and every value here is a number that should line up with the one above it.
 */
export default function IncidentLedger({ incidents, selectedId, onSelect, recentIds }) {
  if (!incidents.length) return <Empty>No incidents yet.</Empty>;

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse text-left">
        <thead>
          <tr className="border-b rule">
            {["Entity", "Decision", "Corroboration", "PS1", "PS2", "Gap", "Landed", ""].map((h, i) => (
              <th key={h + i} className={`pb-2 eyebrow font-semibold ${i >= 3 && i <= 5 ? "pr-6 text-right" : "pr-3"}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {incidents.map((inc) => {
            const by = assessmentsByDomain(inc);
            const sel = inc.incident_id === selectedId;
            const fresh = recentIds?.has(inc.incident_id);
            const d = decisionOf(inc.access_decision);
            const gap = convergenceGapMinutes(inc);

            return (
              <tr
                key={inc.incident_id}
                onClick={() => onSelect(sel ? null : inc.incident_id)}
                className={`group cursor-pointer border-b border-ink-800/70 transition-colors ${
                  sel ? "bg-ink-800/70" : "hover:bg-ink-850"
                } ${fresh ? "animate-fadeIn" : ""}`}
              >
                <td className="py-2.5 pr-3">
                  <div className="flex items-center gap-2">
                    <span className="h-3.5 w-[2px] rounded-full" style={{ background: d.hex, opacity: sel ? 1 : 0.55 }} />
                    <span className="font-mono text-[14.5px] text-chalk">{shortEntity(inc.entity_id)}</span>
                    {fresh && (
                      <span className="rounded-sm border border-good/40 bg-good/10 px-1 font-mono text-micro uppercase text-good">
                        new
                      </span>
                    )}
                  </div>
                </td>
                <td className="py-2.5 pr-3"><DecisionChip decision={inc.access_decision} /></td>
                <td className="py-2.5 pr-3">
                  <CorroborationMark level={inc.confidence} domains={inc.contributing_domains} />
                </td>
                <td className="tnum py-2.5 pr-6 text-right font-mono text-[14.5px]"
                    style={{ color: by.ps1_behavioral ? "#E8A33D" : "#2A3644" }}>
                  {by.ps1_behavioral ? fmtScore(by.ps1_behavioral.score) : "—"}
                </td>
                <td className="tnum py-2.5 pr-6 text-right font-mono text-[14.5px]"
                    style={{ color: by.ps2_transaction ? "#3DC5E8" : "#2A3644" }}>
                  {by.ps2_transaction ? fmtScore(by.ps2_transaction.score) : "—"}
                </td>
                <td className="tnum py-2.5 pr-6 text-right font-mono text-[14px] text-chalk-dim">
                  {isCorroborated(inc) ? fmtGap(gap) : "—"}
                </td>
                <td className="py-2.5 pr-3 font-mono text-micro text-chalk-faint">
                  {incidentTime(inc)
                    ? fmtDateTime(incidentTime(inc))
                    : <span className="text-ink-500">no event time</span>}
                </td>
                <td className="py-2.5 text-right font-mono text-micro text-chalk-faint opacity-0 transition-opacity group-hover:opacity-100">
                  {sel ? "×" : "→"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
