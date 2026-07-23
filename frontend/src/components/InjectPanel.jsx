import React, { useEffect, useState } from "react";
import { ingestBehavioral, ingestTransaction } from "../lib/api.js";
import { DomainTag, Eyebrow } from "./primitives.jsx";

const KEY_STORE = "vw_ingest_key";

/**
 * Live injection: posts an *unscored* input and the server runs the model
 * in-process, then re-correlates. Two steps, on purpose — the first signal
 * lands alone and is capped; the second corroborates it and unlocks revoke.
 */
export default function InjectPanel({ onIngested, onClose }) {
  const [apiKey, setApiKey] = useState(() => sessionStorage.getItem(KEY_STORE) || import.meta.env.VITE_INGESTION_KEY || "");
  const [payloads, setPayloads] = useState(null);
  const [log, setLog] = useState([]);
  const [busy, setBusy] = useState(null);

  useEffect(() => {
    fetch("/demo/live-payloads")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then(setPayloads)
      .catch(() => setPayloads(false));
  }, []);

  useEffect(() => {
    if (apiKey) sessionStorage.setItem(KEY_STORE, apiKey);
  }, [apiKey]);

  const push = (entry) => setLog((l) => [{ ...entry, at: new Date() }, ...l].slice(0, 6));

  async function inject(kind) {
    if (!apiKey) return push({ ok: false, kind, text: "Enter the ingestion API key first." });
    setBusy(kind);
    try {
      const body = payloads[kind].payload;
      const res = kind === "behavioral" ? await ingestBehavioral(body, apiKey) : await ingestTransaction(body, apiKey);
      const fired = res.scored ?? res.alerted;
      push({
        ok: true,
        kind,
        text: fired
          ? `scored ${Number(res.score).toFixed(4)} → ${res.entity_id} · ${res.affected_incident_ids?.length || 0} incident(s) updated`
          : `no alert — ${res.reason || "below threshold"}`,
      });
      onIngested?.(res.affected_incident_ids || []);
    } catch (e) {
      push({ ok: false, kind, text: e.message });
    } finally {
      setBusy(null);
    }
  }

  const steps = [
    {
      kind: "behavioral",
      domain: "ps1_behavioral",
      n: 1,
      title: "Behavioural window",
      body: "A real prepared CERT user-hour window. The server runs the Isolation Forest on it now — nothing is pre-scored.",
      expect: "Lands alone → capped at step-up.",
    },
    {
      kind: "transaction",
      domain: "ps2_transaction",
      n: 2,
      title: "Transaction row",
      body: "A transaction for the same entity, inside the 120-minute window. The fraud model scores it live, with SHAP reasons.",
      expect: "Corroborates → unlocks revoke.",
    },
  ];

  return (
    <div className="animate-riseIn panel p-5">
      <div className="flex items-start justify-between gap-4 border-b rule pb-3">
        <div>
          <h3 className="text-[15px] font-semibold tracking-tight text-chalk">Inject a live signal</h3>
          <p className="mt-1 max-w-xl text-[12.5px] leading-relaxed text-chalk-dim">
            Watch detection happen rather than reading a stored result. The server scores each
            payload in-process, re-runs correlation, and the timeline updates.
          </p>
        </div>
        {onClose && (
          <button onClick={onClose} className="focusable rounded border border-ink-700 px-2 py-1 text-tiny text-chalk-dim hover:border-ink-500 hover:text-chalk">
            Close
          </button>
        )}
      </div>

      {payloads === false ? (
        <p className="mt-4 font-mono text-tiny text-alert-soft">
          Demo payloads unavailable — the API has no committed fixtures at data/synthetic/live_demo_*.json.
        </p>
      ) : (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {steps.map((s) => (
              <div key={s.kind} className="rounded border border-ink-700 bg-ink-900/60 p-3.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-micro text-chalk-faint">STEP {s.n}</span>
                    <DomainTag domain={s.domain} size="xs" />
                  </div>
                </div>
                <div className="mt-2 text-[13px] font-medium text-chalk">{s.title}</div>
                <p className="mt-1 text-[11.5px] leading-relaxed text-chalk-dim">{s.body}</p>
                <p className="mt-1.5 text-[11.5px] italic leading-relaxed text-chalk-faint">{s.expect}</p>
                <button
                  disabled={!payloads || busy}
                  onClick={() => inject(s.kind)}
                  className="focusable mt-3 w-full rounded-sm border px-3 py-2 font-mono text-tiny uppercase tracking-[0.1em] transition-colors disabled:opacity-40"
                  style={{
                    borderColor: `${s.domain === "ps1_behavioral" ? "#E8A33D" : "#3DC5E8"}55`,
                    color: s.domain === "ps1_behavioral" ? "#F0C177" : "#7ADCF3",
                    background: `${s.domain === "ps1_behavioral" ? "#E8A33D" : "#3DC5E8"}10`,
                  }}
                >
                  {busy === s.kind ? "scoring···" : "Inject"}
                </button>
              </div>
            ))}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <label className="flex flex-1 items-center gap-2">
              <span className="eyebrow whitespace-nowrap">Ingestion key</span>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="VAULTWATCH_INGESTION_API_KEY"
                className="focusable min-w-0 flex-1 rounded-sm border border-ink-700 bg-ink-950 px-2.5 py-1.5 font-mono text-tiny text-chalk placeholder:text-chalk-faint/60"
              />
            </label>
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-chalk-faint">
            Demo control: the key is sent from the browser. In a real deployment a detector
            publishes server-side over HTTP or Kafka — the browser never holds this.
          </p>

          {log.length > 0 && (
            <div className="mt-4 border-t rule pt-3">
              <Eyebrow>Response log</Eyebrow>
              <div className="mt-2 space-y-1 font-mono text-micro">
                {log.map((l, i) => (
                  <div key={i} className="flex gap-2.5">
                    <span className="text-chalk-faint">{l.at.toLocaleTimeString("en-GB")}</span>
                    <span style={{ color: l.kind === "behavioral" ? "#E8A33D" : "#3DC5E8" }}>
                      {l.kind === "behavioral" ? "PS1" : "PS2"}
                    </span>
                    <span className={l.ok ? "text-chalk-dim" : "text-alert-soft"}>{l.text}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
