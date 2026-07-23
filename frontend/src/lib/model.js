// Domain + decision vocabulary, and the derived shapes the timeline needs.
// One place so the story reads identically everywhere it appears.

export const DOMAIN = {
  ps1_behavioral: {
    key: "ps1_behavioral",
    tag: "PS1",
    label: "Behavioural",
    long: "Privileged access & insider behaviour",
    hex: "#E8A33D",
    text: "text-ps1",
    bg: "bg-ps1",
    ring: "ring-ps1/40",
    ghost: "bg-ps1-ghost",
    border: "border-ps1/30",
  },
  ps2_transaction: {
    key: "ps2_transaction",
    tag: "PS2",
    label: "Transaction",
    long: "Transaction fraud & telemetry",
    hex: "#3DC5E8",
    text: "text-ps2",
    bg: "bg-ps2",
    ring: "ring-ps2/40",
    ghost: "bg-ps2-ghost",
    border: "border-ps2/30",
  },
};

export const domainOf = (key) =>
  DOMAIN[key] || { key, tag: "—", label: key, long: key, hex: "#5D6B7D", text: "text-chalk-faint", bg: "bg-ink-600", ghost: "bg-ink-800", border: "border-ink-600" };

// Mirrors backend decide_access() exactly. Kept in sync deliberately: the UI
// explains the rule, so it must state the same thresholds the engine applies.
export const DECISION = {
  revoke: {
    key: "revoke",
    label: "Revoke access",
    short: "REVOKE",
    rank: 3,
    rule: "score ≥ 0.90 AND both domains corroborate",
    hex: "#E5484D",
    text: "text-alert",
    bg: "bg-alert",
    chip: "bg-alert/12 text-alert-soft border-alert/30",
  },
  step_up_auth: {
    key: "step_up_auth",
    label: "Step-up authentication",
    short: "STEP-UP",
    rank: 2,
    rule: "score ≥ 0.70",
    hex: "#E8A33D",
    text: "text-ps1",
    bg: "bg-ps1",
    chip: "bg-ps1/12 text-ps1-soft border-ps1/30",
  },
  throttle: {
    key: "throttle",
    label: "Throttle activity",
    short: "THROTTLE",
    rank: 1,
    rule: "score ≥ 0.40",
    hex: "#7ADCF3",
    text: "text-ps2-soft",
    bg: "bg-ps2",
    chip: "bg-ps2/12 text-ps2-soft border-ps2/30",
  },
  allow: {
    key: "allow",
    label: "Allow",
    short: "ALLOW",
    rank: 0,
    rule: "below all thresholds",
    hex: "#3DD68C",
    text: "text-good",
    bg: "bg-good",
    chip: "bg-good/12 text-good border-good/30",
  },
};

export const decisionOf = (key) => DECISION[key] || DECISION.allow;

export const CORRELATION_WINDOW_MIN = 120;

// ---- derived helpers -------------------------------------------------------

export const parseTime = (iso) => (iso ? new Date(iso) : null);

/** Strongest assessment per domain, in a stable order. */
export function assessmentsByDomain(incident) {
  const out = {};
  for (const a of incident.contributing_assessments || []) {
    if (!out[a.domain] || a.score > out[a.domain].score) out[a.domain] = a;
  }
  return out;
}

/** Minutes between the earliest and latest contributing signal. */
export function convergenceGapMinutes(incident) {
  const times = (incident.contributing_assessments || [])
    .map((a) => parseTime(a.event_time))
    .filter(Boolean)
    .sort((a, b) => a - b);
  if (times.length < 2) return null;
  return (times[times.length - 1] - times[0]) / 60000;
}

/**
 * The moment an incident "lands" — its latest contributing evidence.
 * Returns null when no contributing signal carries an event_time: such an
 * incident has no position on a time axis and, per the engine, can never
 * corroborate. Callers must handle null rather than substituting created_at,
 * which is ingestion wall-clock and would corrupt the scale.
 */
export function incidentTime(incident) {
  const times = (incident.contributing_assessments || [])
    .map((a) => parseTime(a.event_time))
    .filter(Boolean)
    .sort((a, b) => a - b);
  return times.length ? times[times.length - 1] : null;
}

export const isCorroborated = (incident) => (incident.contributing_domains || []).length >= 2;

/** Flatten every incident into individual signals, for the single-domain views. */
export function allSignals(incidents) {
  const rows = [];
  for (const inc of incidents) {
    for (const a of inc.contributing_assessments || []) {
      rows.push({ ...a, incident_id: inc.incident_id, decision: inc.access_decision, corroborated: isCorroborated(inc) });
    }
  }
  return rows.sort((a, b) => (parseTime(b.event_time) || 0) - (parseTime(a.event_time) || 0));
}

// ---- formatting ------------------------------------------------------------

const UTC = { timeZone: "UTC" };

export const fmtScore = (n) => (n == null ? "—" : n.toFixed(3).replace(/^0/, "·"));
export const fmtPct = (n) => (n == null ? "—" : `${Math.round(n * 100)}%`);

export const fmtDate = (d) =>
  d ? d.toLocaleDateString("en-GB", { ...UTC, day: "2-digit", month: "short" }) : "—";

export const fmtClock = (d) =>
  d ? d.toLocaleTimeString("en-GB", { ...UTC, hour: "2-digit", minute: "2-digit" }) : "—";

export const fmtDateTime = (d) => (d ? `${fmtDate(d)} ${fmtClock(d)}Z` : "—");

export function fmtGap(minutes) {
  if (minutes == null) return "—";
  if (minutes < 1) return "<1 min";
  // Round to whole minutes *first*: rounding the remainder independently
  // produced "1h 60m" for anything just under two hours.
  const total = Math.round(minutes);
  if (total < 60) return `${total} min`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

/** Shorten an entity id for dense display: "CERT:CET3786" -> "CET3786". */
export const shortEntity = (id) => (id || "").replace(/^CERT:/, "");
