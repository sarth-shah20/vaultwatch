import React from "react";
import { decisionOf, domainOf, fmtScore } from "../lib/model.js";

export function Eyebrow({ children, className = "" }) {
  return <div className={`eyebrow ${className}`}>{children}</div>;
}

export function DomainTag({ domain, size = "sm" }) {
  const d = domainOf(domain);
  const pad = size === "xs" ? "px-1.5 py-px text-micro" : "px-2 py-0.5 text-tiny";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-sm border font-mono font-medium uppercase tracking-wider ${pad}`}
      style={{ color: d.hex, borderColor: `${d.hex}44`, background: `${d.hex}12` }}
    >
      <span className="h-1 w-1 rounded-full" style={{ background: d.hex }} />
      {d.tag}
    </span>
  );
}

export function DecisionChip({ decision, size = "sm" }) {
  const d = decisionOf(decision);
  const pad = size === "lg" ? "px-3 py-1 text-tiny" : "px-2 py-0.5 text-micro";
  return (
    <span
      className={`inline-flex items-center rounded-sm border font-mono font-semibold uppercase tracking-[0.12em] ${pad}`}
      style={{ color: d.hex, borderColor: `${d.hex}4d`, background: `${d.hex}14` }}
    >
      {d.short}
    </span>
  );
}

/** Corroboration is a count of agreeing domains — never a probability. */
export function CorroborationMark({ level, domains = [] }) {
  const high = level === "high";
  return (
    <span className="inline-flex items-center gap-1.5" title={high ? "Two independent domains agreed inside the window" : "Only one domain fired"}>
      <span className="flex items-center gap-0.5">
        {["ps1_behavioral", "ps2_transaction"].map((k) => {
          const on = domains.includes(k);
          const d = domainOf(k);
          return (
            <span
              key={k}
              className="h-2.5 w-1 rounded-[1px] transition-colors"
              style={{ background: on ? d.hex : "#1E2833" }}
            />
          );
        })}
      </span>
      <span className={`font-mono text-micro uppercase tracking-[0.12em] ${high ? "text-chalk" : "text-chalk-faint"}`}>
        {high ? "corroborated" : "lone"}
      </span>
    </span>
  );
}

/** Score rendered as a precise numeral plus a hairline meter. */
export function ScoreMeter({ value, hex = "#E7ECF3", width = 44 }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="tnum font-mono text-[15px] tabular-nums" style={{ color: hex }}>
        {fmtScore(value)}
      </span>
      <span className="relative block h-[3px] overflow-hidden rounded-full bg-ink-700" style={{ width }}>
        <span
          className="absolute inset-y-0 left-0 origin-left animate-growX rounded-full"
          style={{ width: `${Math.max(2, (value || 0) * 100)}%`, background: hex }}
        />
      </span>
    </span>
  );
}

export function Panel({ children, className = "" }) {
  return <div className={`panel ${className}`}>{children}</div>;
}

export function SectionHead({ title, caption, right }) {
  return (
    <div className="mb-4 flex items-end justify-between gap-6 border-b rule pb-2.5">
      <div>
        <h2 className="text-[17px] font-semibold tracking-tight text-chalk">{title}</h2>
        {caption && <p className="mt-1 max-w-2xl text-[14.5px] leading-relaxed text-chalk-dim">{caption}</p>}
      </div>
      {right}
    </div>
  );
}

export function Skeleton({ className = "" }) {
  return (
    <div className={`relative overflow-hidden rounded bg-ink-800 ${className}`}>
      <div className="absolute inset-y-0 w-1/3 animate-sweep bg-gradient-to-r from-transparent via-white/[0.05] to-transparent" />
    </div>
  );
}

export function ErrorNote({ error, onRetry }) {
  return (
    <div className="panel border-alert/30 bg-alert-ghost/60 p-6">
      <Eyebrow className="text-alert-soft">API unreachable</Eyebrow>
      <p className="mt-2 text-sm text-chalk">
        The correlation API isn’t responding. Start it, then retry.
      </p>
      <pre className="mt-3 overflow-x-auto rounded border border-ink-700 bg-ink-950 p-3 font-mono text-tiny text-chalk-dim">
        python3 -m uvicorn backend.app.main:app --port 8000
      </pre>
      {error && <p className="mt-2 font-mono text-micro text-chalk-faint">{String(error.message || error)}</p>}
      {onRetry && (
        <button onClick={onRetry} className="focusable mt-4 rounded border border-ink-600 px-3 py-1.5 text-tiny text-chalk hover:border-ink-500 hover:bg-ink-800">
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children }) {
  return (
    <div className="flex items-center justify-center rounded border border-dashed border-ink-700 px-6 py-14 text-center text-[15px] text-chalk-faint">
      {children}
    </div>
  );
}
