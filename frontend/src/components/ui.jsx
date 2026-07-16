import React, { useEffect, useRef, useState } from "react";
import { CONFIDENCE, DECISIONS, DOMAINS, fmtScore } from "../theme.js";

/* ---------- animated number (score count-up) ---------- */
export function useCountUp(target, duration = 900) {
  const [value, setValue] = useState(0);
  const raf = useRef();
  useEffect(() => {
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(target * eased);
      if (t < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, duration]);
  return value;
}

/* ---------- circular score gauge ---------- */
const GAUGE_TONES = {
  revoke: ["#8f2f3d", "#5c1a24"],
  step_up_auth: ["#c98f2a", "#8a5a13"],
  throttle: ["#4a7bab", "#24507a"],
  allow: ["#c7d7e6", "#9db8cf"],
};

export function ScoreGauge({ score, size = 64, stroke = 5, decision }) {
  const animated = useCountUp(score);
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const [from, to] = GAUGE_TONES[decision] || GAUGE_TONES.allow;
  const gid = `gg-${decision || "allow"}-${size}`;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <defs>
          <linearGradient id={gid} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={from} />
            <stop offset="100%" stopColor={to} />
          </linearGradient>
        </defs>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="#e9eef5"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={`url(#${gid})`}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - animated)}
          style={{ filter: `drop-shadow(0 1px 2px ${to}33)` }}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="font-mono font-semibold tabular-nums text-vault-900" style={{ fontSize: size * 0.25 }}>
          {fmtScore(animated)}
        </span>
      </div>
    </div>
  );
}

/* ---------- badges & chips ---------- */
export function DecisionBadge({ decision, size = "md" }) {
  const d = DECISIONS[decision] || DECISIONS.allow;
  const pad = size === "lg" ? "px-4 py-1.5 text-sm" : "px-2.5 py-1 text-xs";
  return (
    <span className={`inline-flex items-center rounded-full font-semibold tracking-wide ${pad} ${d.badge}`}>
      {d.short}
    </span>
  );
}

export function ConfidenceBadge({ confidence }) {
  const c = CONFIDENCE[confidence] || CONFIDENCE.low;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${c.chip}`}
      title={c.note}
    >
      {confidence === "high" && (
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden>
          <path d="M1.5 5.2 4 7.7 8.5 2.6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      )}
      {c.label}
    </span>
  );
}

export function DomainIcon({ domain, className = "" }) {
  if (domain === "ps1_behavioral")
    return (
      <svg viewBox="0 0 16 16" fill="none" className={className} aria-hidden>
        <circle cx="8" cy="5" r="2.6" stroke="currentColor" strokeWidth="1.4" />
        <path d="M2.8 13.4c.7-2.6 2.8-4 5.2-4s4.5 1.4 5.2 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
    );
  return (
    <svg viewBox="0 0 16 16" fill="none" className={className} aria-hidden>
      <rect x="1.8" y="3.4" width="12.4" height="9.2" rx="1.6" stroke="currentColor" strokeWidth="1.4" />
      <path d="M1.8 6.4h12.4" stroke="currentColor" strokeWidth="1.4" />
      <path d="M4.4 9.8h3.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export function DomainChip({ domain }) {
  const d = DOMAINS[domain];
  if (!d) return null;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-medium ${d.chip}`}>
      <DomainIcon domain={domain} className="h-3 w-3" />
      {d.name}
    </span>
  );
}

export function CorroborationMark() {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md bg-vault-900 px-2 py-0.5 text-[11px] font-medium text-white"
      title="Independent domains agree — confidence raised to high"
    >
      <svg width="10" height="10" viewBox="0 0 12 12" fill="none" aria-hidden>
        <path d="M4.2 3 1.6 6l2.6 3M7.8 3l2.6 3-2.6 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Corroborated
    </span>
  );
}

/* ---------- legend: the UI explains its own logic ---------- */
export function DecisionLegend() {
  const tiers = ["allow", "throttle", "step_up_auth", "revoke"];
  return (
    <div className="rounded-2xl border border-vault-100 bg-white/85 px-5 py-4 shadow-card backdrop-blur-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="mr-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-vault-400">
          Response ladder
        </span>
        {tiers.map((t, i) => {
          const d = DECISIONS[t];
          return (
            <React.Fragment key={t}>
              {i > 0 && (
                <svg width="14" height="8" viewBox="0 0 14 8" fill="none" className="text-vault-200" aria-hidden>
                  <path d="M0 4h11m0 0L8 1m3 3L8 7" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
                </svg>
              )}
              <span
                className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-semibold ${d.chip}`}
                title={d.trigger}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${d.bar}`} />
                {d.short}
              </span>
            </React.Fragment>
          );
        })}
      </div>
      <p className="mt-2.5 border-t border-vault-50 pt-2.5 text-xs leading-relaxed text-vault-500">
        One domain firing alone is treated cautiously — <span className="font-medium text-vault-700">verify or limit, never lock out</span>.
        Only when independent behavioral and transaction signals corroborate for the same person does
        confidence reach high and access get revoked. That asymmetry is the false-positive defense.
      </p>
    </div>
  );
}

/* ---------- loading & error states ---------- */
export function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-2xl border border-vault-100 bg-white p-5 shadow-card">
      <div className="flex items-center gap-4">
        <div className="h-16 w-16 rounded-full bg-vault-100" />
        <div className="flex-1 space-y-2.5">
          <div className="h-3.5 w-40 rounded bg-vault-100" />
          <div className="h-3 w-64 rounded bg-vault-50" />
          <div className="h-3 w-24 rounded bg-vault-50" />
        </div>
        <div className="h-6 w-20 rounded-full bg-vault-100" />
      </div>
    </div>
  );
}

export function ErrorState({ onRetry }) {
  return (
    <div className="mx-auto max-w-md animate-rise rounded-2xl border border-vault-100 bg-white p-8 text-center shadow-card">
      <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-vault-50">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
          <path d="M10 6.5v4.5m0 2.8v.2" stroke="#33628c" strokeWidth="1.8" strokeLinecap="round" />
          <circle cx="10" cy="10" r="8" stroke="#33628c" strokeWidth="1.6" />
        </svg>
      </div>
      <h3 className="font-display text-lg font-semibold text-vault-900">
        Can&rsquo;t reach the VaultWatch API
      </h3>
      <p className="mt-2 text-sm leading-relaxed text-vault-500">
        The correlation service on{" "}
        <code className="rounded bg-vault-50 px-1.5 py-0.5 font-mono text-xs">localhost:8000</code>{" "}
        didn&rsquo;t respond. Make sure the backend is running, then retry.
      </p>
      <button
        onClick={onRetry}
        className="mt-5 rounded-lg bg-vault-900 px-5 py-2 text-sm font-semibold text-white transition hover:bg-vault-800 active:scale-[0.98]"
      >
        Retry connection
      </button>
    </div>
  );
}
