import React, { useEffect, useState } from "react";
import { getQuantumReport } from "../lib/api.js";
import { Empty, ErrorNote, Eyebrow, SectionHead, Skeleton } from "./primitives.jsx";

const TIER = {
  CRITICAL: "#E5484D",
  HIGH: "#E8A33D",
  MEDIUM: "#3DC5E8",
  LOW: "#3A4757",
};

function Stat({ label, value, sub, hex }) {
  return (
    <div>
      <Eyebrow>{label}</Eyebrow>
      <div className="tnum mt-1 font-mono text-[28px] leading-none" style={{ color: hex || "#E7ECF3" }}>{value}</div>
      {sub && <div className="mt-1 text-[13.5px] text-chalk-faint">{sub}</div>}
    </div>
  );
}

export default function QuantumView() {
  const [state, setState] = useState({ phase: "loading" });

  useEffect(() => {
    let live = true;
    getQuantumReport()
      .then((data) => live && setState({ phase: "ready", data }))
      .catch((error) => live && setState({ phase: "error", error }));
    return () => { live = false; };
  }, []);

  if (state.phase === "loading") {
    return <div className="space-y-3"><Skeleton className="h-20" /><Skeleton className="h-64" /></div>;
  }
  if (state.phase === "error") return <ErrorNote error={state.error} />;

  const { summary, migration_priority: assets } = state.data;
  const maxScore = Math.max(...assets.map((a) => a.priority_score), 1);

  return (
    <div className="animate-fadeIn">
      <SectionHead
        title="Quantum exposure · PQC migration priority"
        caption="This is an inventory-and-prioritisation tool, not a detector. Passive harvest-now-decrypt-later activity leaves no observable signal, so nothing here claims to catch it happening. What it does: rank which systems to migrate first, by algorithm vulnerability × data sensitivity × how long that data must stay secret."
      />

      <div className="panel mb-6 grid grid-cols-2 gap-6 p-5 sm:grid-cols-4">
        <Stat label="Assets" value={summary.assets} />
        <Stat label="Quantum-vulnerable" value={summary.quantum_vulnerable} hex="#E8A33D" sub="RSA / ECC / DH families" />
        <Stat label="HNDL-exposed" value={summary.hndl_exposed} hex="#E5484D" sub="vulnerable + sensitive + long-lived" />
        <Stat label="Critical tier" value={summary.by_tier?.CRITICAL ?? 0} hex="#E5484D" sub="migrate first" />
      </div>

      {!assets.length ? (
        <Empty>Inventory is empty.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] border-collapse text-left">
            <thead>
              <tr className="border-b rule">
                {["System", "Data flow", "Algorithm", "Sensitivity", "Retention", "Priority", "Migrate to"].map((h, i) => (
                  <th key={h} className={`pb-2 eyebrow font-semibold ${i === 4 || i === 5 ? "pr-6 text-right" : "pr-3"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {assets.map((a, i) => {
                const hex = TIER[a.priority_tier] || "#3A4757";
                return (
                  <tr key={i} className="border-b border-ink-800/70 transition-colors hover:bg-ink-850">
                    <td className="py-2.5 pr-3">
                      <div className="flex items-center gap-2">
                        <span className="h-3.5 w-[2px] rounded-full" style={{ background: hex }} />
                        <span className="text-[14.5px] text-chalk">{a.system}</span>
                        {a.hndl_risk && (
                          <span className="rounded-sm border border-alert/40 bg-alert/10 px-1.5 font-mono text-micro uppercase tracking-wider text-alert-soft"
                                title="Vulnerable algorithm + sensitive data + 5y+ confidentiality: harvest today, decrypt later.">
                            HNDL
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-2.5 pr-3 text-[13.5px] text-chalk-dim">{a.data_flow}</td>
                    <td className="py-2.5 pr-3 font-mono text-[13.5px]"
                        style={{ color: a.quantum_status === "quantum_vulnerable" ? "#F0C177" : "#95A2B3" }}>
                      {a.crypto_algorithm}
                    </td>
                    <td className="py-2.5 pr-3 font-mono text-micro uppercase tracking-wider text-chalk-dim">
                      {a.data_sensitivity}
                    </td>
                    <td className="tnum py-2.5 pr-6 text-right font-mono text-[13.5px] text-chalk-dim">
                      {a.retention_years}y
                    </td>
                    <td className="py-2.5 pr-6">
                      <div className="flex items-center justify-end gap-2">
                        <span className="tnum font-mono text-[14.5px]" style={{ color: hex }}>
                          {a.priority_score.toFixed(2)}
                        </span>
                        <span className="h-[3px] w-14 overflow-hidden rounded-full bg-ink-700">
                          <span className="block h-full origin-left animate-growX rounded-full"
                                style={{ width: `${(a.priority_score / maxScore) * 100}%`, background: hex, animationDelay: `${i * 30}ms` }} />
                        </span>
                      </div>
                    </td>
                    <td className="py-2.5 font-mono text-[13.5px] text-chalk-dim">{a.recommended_pqc}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
