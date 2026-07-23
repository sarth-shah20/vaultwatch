import React, { useMemo } from "react";
import {
  allSignals,
  domainOf,
  fmtDateTime,
  fmtScore,
  parseTime,
  shortEntity,
} from "../lib/model.js";
import { Empty, Eyebrow, SectionHead } from "./primitives.jsx";

/** Score distribution — makes each detector's own character visible. */
function Distribution({ values, hex }) {
  const bins = useMemo(() => {
    const b = new Array(10).fill(0);
    values.forEach((v) => b[Math.min(9, Math.floor(v * 10))]++);
    return b;
  }, [values]);
  const max = Math.max(1, ...bins);

  return (
    <div>
      <div className="flex h-20 items-end gap-[3px]">
        {bins.map((n, i) => (
          <div key={i} className="group relative flex-1" title={`${(i / 10).toFixed(1)}–${((i + 1) / 10).toFixed(1)}: ${n}`}>
            <div className="w-full rounded-[1px] transition-all"
                 style={{ height: `${(n / max) * 76}px`, background: n ? hex : "#1A222C", opacity: n ? 0.35 + 0.65 * (n / max) : 1 }} />
          </div>
        ))}
      </div>
      <div className="mt-1.5 flex justify-between font-mono text-micro text-chalk-faint">
        <span>0·0</span><span>0·5</span><span>1·0</span>
      </div>
    </div>
  );
}

export default function DomainView({ domain, incidents, onSelect }) {
  const d = domainOf(domain);
  const signals = useMemo(
    () => allSignals(incidents).filter((s) => s.domain === domain),
    [incidents, domain]
  );

  const scores = signals.map((s) => s.score);
  const corroborated = signals.filter((s) => s.corroborated).length;
  const mean = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;

  const blurb =
    domain === "ps1_behavioral"
      ? "What the behavioural model sees on its own, before correlation. Scores are an empirical percentile against a validation population — a relative behavioural risk, deliberately not a calibrated probability."
      : "What the fraud model sees on its own, before correlation. Scores come from a gradient-boosted model over PaySim transaction features; each reason is that transaction’s own SHAP contribution.";

  return (
    <div className="animate-fadeIn">
      <SectionHead
        title={`${d.tag} · ${d.long}`}
        caption={blurb}
        right={
          <div className="flex gap-8 text-right">
            <div>
              <Eyebrow>Signals</Eyebrow>
              <div className="tnum mt-0.5 font-mono text-xl" style={{ color: d.hex }}>{signals.length}</div>
            </div>
            <div>
              <Eyebrow>Corroborated</Eyebrow>
              <div className="tnum mt-0.5 font-mono text-xl text-chalk">
                {corroborated}
                <span className="text-sm text-chalk-faint">/{signals.length}</span>
              </div>
            </div>
            <div>
              <Eyebrow>Mean</Eyebrow>
              <div className="tnum mt-0.5 font-mono text-xl text-chalk-dim">{fmtScore(mean)}</div>
            </div>
          </div>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <div>
          <Eyebrow>Score distribution</Eyebrow>
          <div className="mt-3 panel p-4">
            <Distribution values={scores} hex={d.hex} />
          </div>
          <p className="mt-3 text-[11.5px] leading-relaxed text-chalk-faint">
            {domain === "ps2_transaction"
              ? "The fraud model is near-binary — scores pile up at the extremes rather than spreading across the range. A known, documented property of training on PaySim."
              : "Only windows above the 0·99 operational alert threshold are surfaced at all, so this view is the extreme tail by construction."}
          </p>
        </div>

        <div>
          <Eyebrow>Signals</Eyebrow>
          <div className="mt-3 overflow-x-auto">
            {signals.length === 0 ? (
              <Empty>No {d.label.toLowerCase()} signals.</Empty>
            ) : (
              <table className="w-full min-w-[620px] border-collapse text-left">
                <thead>
                  <tr className="border-b rule">
                    {["Entity", "Score", "Top driver", "Event time", "Alone?"].map((h, i) => (
                      <th key={h} className={`pb-2 eyebrow font-semibold ${i === 1 ? "pr-6 text-right" : "pr-3"}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {signals.map((s) => (
                    <tr key={s.assessment_id}
                        onClick={() => onSelect?.(s.incident_id)}
                        className="cursor-pointer border-b border-ink-800/70 transition-colors hover:bg-ink-850">
                      <td className="py-2 pr-3 font-mono text-[12.5px] text-chalk">{shortEntity(s.entity_id)}</td>
                      <td className="tnum py-2 pr-6 text-right font-mono text-[12.5px]" style={{ color: d.hex }}>
                        {fmtScore(s.score)}
                      </td>
                      <td className="max-w-[280px] truncate py-2 pr-3 font-mono text-[11.5px] text-chalk-dim"
                          title={s.reasons?.[0]?.raw_value}>
                        {s.reasons?.[0]?.signal_name || "—"}
                      </td>
                      <td className="py-2 pr-3 font-mono text-micro text-chalk-faint">
                        {fmtDateTime(parseTime(s.event_time))}
                      </td>
                      <td className="py-2 font-mono text-micro">
                        {s.corroborated
                          ? <span className="text-chalk-faint">paired</span>
                          : <span className="text-ps1-soft">lone</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
