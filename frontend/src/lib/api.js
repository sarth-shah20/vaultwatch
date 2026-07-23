// All calls are same-origin and proxied to FastAPI by vite (see vite.config.js).

async function get(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`);
  return res.json();
}

async function post(path, body, key) {
  const headers = { "Content-Type": "application/json" };
  if (key) headers["X-Ingestion-API-Key"] = key;
  const res = await fetch(path, { method: "POST", headers, body: JSON.stringify(body) });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = payload?.detail || `${res.status} ${res.statusText}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

export const getHealth = () => get("/health");
export const getIncidents = () => get("/incidents");
export const getProviders = () => get("/providers");
export const getQuantumReport = () => get("/quantum/report");
export const getSuppressions = () => get("/suppressions");

export const sendFeedback = (id, action, reason) =>
  post(`/incidents/${id}/feedback`, { action, reason, analyst: "analyst" });

// Live in-process scoring. The server runs the model on these payloads.
export const ingestBehavioral = (payload, key) => post("/ingest/behavioral", payload, key);
export const ingestTransaction = (payload, key) => post("/ingest/transaction", payload, key);
