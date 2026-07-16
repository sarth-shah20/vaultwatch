// Thin API client. Same-origin paths; Vite proxies them to FastAPI on :8000.

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (err) {
    const e = new Error("network");
    e.kind = "network";
    throw e;
  }
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const e = new Error(body?.detail || `HTTP ${res.status}`);
    e.kind = "http";
    e.status = res.status;
    e.body = body;
    throw e;
  }
  return body;
}

export const getHealth = () => request("/health");
export const getIncidents = () => request("/incidents");
export const getSuppressions = () => request("/suppressions");
export const sendFeedback = (incidentId, action, reason) =>
  request(`/incidents/${incidentId}/feedback`, {
    method: "POST",
    body: JSON.stringify(reason ? { action, reason } : { action }),
  });
