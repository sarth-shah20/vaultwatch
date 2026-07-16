import React, { useCallback, useEffect, useState } from "react";
import { getHealth, getIncidents } from "./api.js";
import IncidentDetail from "./components/IncidentDetail.jsx";
import IncidentList from "./components/IncidentList.jsx";
import SignalsView from "./components/SignalsView.jsx";
import { ErrorState, SkeletonCard } from "./components/ui.jsx";

const TABS = [
  { id: "unified", label: "Unified incidents" },
  { id: "ps1", label: "PS1 · Behavioral" },
  { id: "ps2", label: "PS2 · Transactions" },
];

function Wordmark() {
  return (
    <div className="flex items-center gap-3">
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-vault-900 text-white shadow-card">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden>
          <path d="M9 1.8 15.4 4.3v4.2c0 4-2.7 6.7-6.4 7.7-3.7-1-6.4-3.7-6.4-7.7V4.3L9 1.8Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
          <path d="M6.2 8.9l2 2 3.6-3.9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      <div>
        <h1 className="font-display text-xl font-bold leading-none tracking-tight text-vault-950">
          VaultWatch
        </h1>
        <p className="mt-1 text-[11px] font-medium uppercase tracking-[0.16em] text-vault-400">
          Cross-domain security correlation
        </p>
      </div>
    </div>
  );
}

function HealthPill({ health }) {
  const ok = health?.status === "ok";
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${
        ok ? "border-vault-100 bg-white text-vault-700" : "border-[#eeddbb] bg-[#fbf4e6] text-[#7a4f10]"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "animate-pulseDot bg-emerald-500" : "bg-[#b07a20]"}`} />
      {ok ? `Operational · ${health.incidents} incidents` : "API unreachable"}
    </span>
  );
}

export default function App() {
  const [state, setState] = useState({ phase: "loading", incidents: [], health: null });
  const [tab, setTab] = useState("unified");
  const [selectedId, setSelectedId] = useState(null);

  const load = useCallback(async () => {
    setState((s) => ({ ...s, phase: "loading" }));
    try {
      const [health, listing] = await Promise.all([getHealth(), getIncidents()]);
      setState({ phase: "ready", incidents: listing.incidents || [], health });
    } catch {
      setState({ phase: "error", incidents: [], health: null });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const applyUpdate = (updated) =>
    setState((s) => ({
      ...s,
      incidents: s.incidents.map((i) => (i.incident_id === updated.incident_id ? updated : i)),
    }));

  const selected = state.incidents.find((i) => i.incident_id === selectedId) || null;

  return (
    <div className="min-h-screen">
      {/* header */}
      <header className="sticky top-0 z-10 border-b border-vault-100/80 bg-[#f8f9fb]/90 backdrop-blur">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-5 py-4">
          <Wordmark />
          <HealthPill health={state.health} />
        </div>
        {/* domain toggle */}
        <div className="mx-auto max-w-5xl px-5">
          <nav className="-mb-px flex gap-1">
            {TABS.map((t) => {
              const active = tab === t.id;
              return (
                <button
                  key={t.id}
                  onClick={() => {
                    setTab(t.id);
                    setSelectedId(null);
                  }}
                  className={`rounded-t-lg border-b-2 px-4 py-2.5 text-sm font-medium transition ${
                    active
                      ? "border-vault-900 text-vault-950"
                      : "border-transparent text-vault-400 hover:text-vault-700"
                  }`}
                >
                  {t.label}
                </button>
              );
            })}
          </nav>
        </div>
      </header>

      {/* body */}
      <main className="mx-auto max-w-5xl px-5 py-8">
        {state.phase === "loading" && (
          <div className="space-y-3">
            {[0, 1, 2, 3, 4].map((i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        )}

        {state.phase === "error" && <ErrorState onRetry={load} />}

        {state.phase === "ready" &&
          (tab === "unified" ? (
            selected ? (
              <IncidentDetail incident={selected} onBack={() => setSelectedId(null)} onUpdated={applyUpdate} />
            ) : (
              <IncidentList incidents={state.incidents} onOpen={(i) => setSelectedId(i.incident_id)} />
            )
          ) : (
            <SignalsView
              incidents={state.incidents}
              domainKey={tab === "ps1" ? "ps1_behavioral" : "ps2_transaction"}
            />
          ))}
      </main>

      <footer className="mx-auto max-w-5xl px-5 pb-8">
        <p className="border-t border-vault-100 pt-4 text-center text-[11px] text-vault-300">
          VaultWatch · FinSpark 2026 · Correlated detection across behavioral and transaction domains
        </p>
      </footer>
    </div>
  );
}
