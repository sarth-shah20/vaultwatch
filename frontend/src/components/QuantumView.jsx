import React, { useEffect, useState } from "react";
import { getQuantumReport } from "../api.js";
import { useCountUp } from "./ui.jsx";

const TIERS = {
  CRITICAL: { badge: "bg-[#5c1a24] text-[#fdf3f4]", bar: "bg-[#7a2733]", ring: "ring-[#efd3d7]" },
  HIGH: { badge: "bg-[#8a5a13] text-[#fdf8ef]", bar: "bg-[#b07a20]", ring: "ring-[#eeddbb]" },
  MEDIUM: { badge: "bg-vault-100 text-vault-800", bar: "bg-vault-500", ring: "ring-vault-200" },
  LOW: { badge: "bg-white text-vault-500 border border-vault-200", bar: "bg-vault-200", ring: "ring-vault-100" },
};

const STATUS_LABEL = {
  quantum_vulnerable: { text: "Quantum-vulnerable", cls: "text-[#7a2733]" },
  quantum_weakened: { text: "Quantum-weakened", cls: "text-[#8a5a13]" },
  legacy_broken: { text: "Legacy / broken", cls: "text-[#7a2733]" },
  broken: { text: "Broken", cls: "text-[#7a2733]" },
  quantum_safe: { text: "Quantum-safe", cls: "text-emerald-700" },
  quantum_adequate: { text: "Adequate", cls: "text-emerald-700" },
  unknown: { text: "Unknown", cls: "text-vault-500" },
};

function Stat({ label, value, sub, tone = "text-vault-950" }) {
  const animated = useCountUp(value, 700);
  return (
    <div className="flex-1 rounded-2xl border border-vault-100 bg-white px-5 py-4 shadow-card">
      <p className={`font-display text-3xl font-semibold tabular-nums ${tone}`}>
        {Math.round(animated)}
      </p>
      <p className="mt-0.5 text-xs font-semibold text-vault-700">{label}</p>
      {sub && <p className="mt-0.5 text-[11px] leading-snug text-vault-400">{sub}</p>}
    </div>
  );
}

function TierDistribution({ byTier, total }) {
  const order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
  return (
    <div className="rounded-2xl border border-vault-100 bg-white px-5 py-4 shadow-card">
      <div className="flex items-baseline justify-between">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-vault-400">
          Migration priority tiers
        </p>
        <p className="text-[11px] text-vault-400">{total} assets</p>
      </div>
      <div className="mt-3 flex h-2.5 overflow-hidden rounded-full">
        {order.map((t) =>
          byTier[t] ? (
            <div
              key={t}
              className={`${TIERS[t].bar} transition-all duration-700`}
              style={{ width: `${(byTier[t] / total) * 100}%` }}
              title={`${t}: ${byTier[t]}`}
            />
          ) : null
        )}
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1">
        {order.map((t) => (
          <span key={t} className="inline-flex items-center gap-1.5 text-[11px] text-vault-600">
            <span className={`h-1.5 w-1.5 rounded-full ${TIERS[t].bar}`} />
            <span className="font-semibold">{t.charAt(0) + t.slice(1).toLowerCase()}</span>
            <span className="tabular-nums text-vault-400">{byTier[t] || 0}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function AssetRow({ asset, index }) {
  const tier = TIERS[asset.priority_tier] || TIERS.LOW;
  const status = STATUS_LABEL[asset.quantum_status] || STATUS_LABEL.unknown;
  const pct = Math.round(asset.priority_score * 100);
  return (
    <div
      className={`animate-rise flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-4 ${
        index > 0 ? "border-t border-vault-50" : ""
      }`}
      style={{ animationDelay: `${index * 40}ms` }}
    >
      <span className={`w-20 shrink-0 rounded-full px-2.5 py-1 text-center text-[10px] font-bold tracking-wide ${tier.badge}`}>
        {asset.priority_tier}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2.5">
          <p className="text-sm font-semibold text-vault-900">{asset.system}</p>
          <span className="font-mono text-[11px] text-vault-400">{asset.crypto_algorithm}</span>
          {asset.hndl_risk && (
            <span
              className="rounded-md bg-[#fbeef0] px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-[#5c1a24] ring-1 ring-[#efd3d7]"
              title="Harvest-now-decrypt-later: long-lived confidential data behind quantum-vulnerable crypto — ciphertext captured today can be decrypted later"
            >
              HNDL
            </span>
          )}
        </div>
        <p className="mt-0.5 truncate text-xs text-vault-500">
          {asset.data_flow} · {asset.data_sensitivity} · retained {asset.retention_years}y ·{" "}
          <span className={`font-medium ${status.cls}`}>{status.text}</span>
        </p>
      </div>

      <div className="hidden w-32 sm:block">
        <div className="flex items-baseline justify-between">
          <span className="text-[10px] uppercase tracking-wider text-vault-400">priority</span>
          <span className="font-mono text-xs font-semibold text-vault-800">
            {asset.priority_score.toFixed(2)}
          </span>
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-vault-50">
          <div className={`h-full ${tier.bar} transition-[width] duration-700`} style={{ width: `${pct}%` }} />
        </div>
      </div>

      <div className="w-40 shrink-0 text-right">
        <p className="text-[10px] uppercase tracking-wider text-vault-400">migrate to</p>
        <p className="mt-0.5 text-xs font-semibold text-vault-800">{asset.recommended_pqc}</p>
      </div>
    </div>
  );
}

export default function QuantumView() {
  const [state, setState] = useState({ phase: "loading", report: null });

  useEffect(() => {
    let alive = true;
    getQuantumReport()
      .then((report) => alive && setState({ phase: "ready", report }))
      .catch(() => alive && setState({ phase: "error", report: null }));
    return () => {
      alive = false;
    };
  }, []);

  if (state.phase === "loading")
    return (
      <div className="animate-pulse space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-24 rounded-2xl border border-vault-100 bg-white shadow-card" />
          ))}
        </div>
        <div className="h-64 rounded-2xl border border-vault-100 bg-white shadow-card" />
      </div>
    );

  if (state.phase === "error")
    return (
      <p className="rounded-xl border border-vault-100 bg-white p-6 text-center text-sm text-vault-500">
        Couldn&rsquo;t load the quantum report — is the backend running?
      </p>
    );

  const { summary, migration_priority } = state.report;

  return (
    <div className="animate-fadein space-y-4">
      {/* framing */}
      <div className="rounded-2xl border border-vault-100 bg-white p-5 shadow-card">
        <h2 className="font-display text-xl font-semibold text-vault-950">
          Post-quantum readiness
        </h2>
        <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-vault-600">
          An inventory of every cryptographic dependency in the bank, scored by{" "}
          <span className="font-medium text-vault-800">algorithm vulnerability × data sensitivity × confidentiality lifetime</span>.
          Assets marked <span className="font-bold text-[#5c1a24]">HNDL</span> hold long-lived confidential
          data behind quantum-vulnerable crypto — an adversary can harvest that ciphertext{" "}
          <em>today</em> and decrypt it once a quantum computer arrives, so they migrate first.
        </p>
      </div>

      {/* summary stats */}
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Crypto assets inventoried" value={summary.assets} sub="Systems & data flows using cryptography" />
        <Stat
          label="Quantum-vulnerable"
          value={summary.quantum_vulnerable}
          sub="RSA / ECC — broken by Shor's algorithm"
          tone="text-[#8a5a13]"
        />
        <Stat
          label="HNDL-exposed"
          value={summary.hndl_exposed}
          sub="Harvest-now-decrypt-later targets — migrate first"
          tone="text-[#5c1a24]"
        />
      </div>

      <TierDistribution byTier={summary.by_tier} total={summary.assets} />

      {/* prioritized migration list */}
      <div>
        <div className="flex items-baseline justify-between px-1 pb-2">
          <h3 className="font-display text-lg font-semibold text-vault-900">
            PQC migration priority
          </h3>
          <p className="text-[11px] text-vault-400">
            NIST-standardized replacements: ML-KEM (Kyber) · ML-DSA (Dilithium)
          </p>
        </div>
        <div className="overflow-hidden rounded-2xl border border-vault-100 bg-white shadow-card">
          {migration_priority.map((asset, i) => (
            <AssetRow key={`${asset.system}-${i}`} asset={asset} index={i} />
          ))}
        </div>
      </div>
    </div>
  );
}
