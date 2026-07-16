// Visual language for the four decision tiers and the two signal domains.
// One place to keep the story consistent everywhere it appears.

export const DECISIONS = {
  revoke: {
    label: "Revoke access",
    short: "Revoke",
    rank: 3,
    trigger: "Both domains corroborate at high score",
    // Serious and controlled — deep oxblood, not flashing-alarm red.
    badge: "bg-[#5c1a24] text-[#fdf3f4] border border-[#5c1a24]",
    chip: "bg-[#fbeef0] text-[#5c1a24] border border-[#efd3d7]",
    bar: "bg-[#7a2733]",
    edge: "border-l-[#5c1a24]",
  },
  step_up_auth: {
    label: "Step-up authentication",
    short: "Step-up auth",
    rank: 2,
    trigger: "One strong signal, uncorroborated",
    badge: "bg-[#8a5a13] text-[#fdf8ef] border border-[#8a5a13]",
    chip: "bg-[#fbf4e6] text-[#7a4f10] border border-[#eeddbb]",
    bar: "bg-[#b07a20]",
    edge: "border-l-[#8a5a13]",
  },
  throttle: {
    label: "Throttle activity",
    short: "Throttle",
    rank: 1,
    trigger: "One moderate signal, uncorroborated",
    badge: "bg-vault-100 text-vault-800 border border-vault-200",
    chip: "bg-vault-50 text-vault-700 border border-vault-200",
    bar: "bg-vault-500",
    edge: "border-l-vault-500",
  },
  allow: {
    label: "Allow",
    short: "Allow",
    rank: 0,
    trigger: "No significant risk detected",
    badge: "bg-white text-vault-500 border border-vault-200",
    chip: "bg-white text-vault-500 border border-vault-100",
    bar: "bg-vault-200",
    edge: "border-l-vault-200",
  },
};

export const DOMAINS = {
  ps1_behavioral: {
    key: "ps1_behavioral",
    name: "Behavioral",
    system: "PS1 · Insider-threat detection",
    describes: "Logins, device activity, security events",
    chip: "bg-ps1-tint text-ps1-deep border border-ps1-edge",
    panel: "bg-ps1-tint/60 border-ps1-edge",
    header: "text-ps1-deep",
    bar: "bg-ps1-ink",
    dot: "bg-ps1-ink",
  },
  ps2_transaction: {
    key: "ps2_transaction",
    name: "Transaction",
    system: "PS2 · Fraud detection",
    describes: "Payments, transfers, balance movements",
    chip: "bg-ps2-tint text-ps2-deep border border-ps2-edge",
    panel: "bg-ps2-tint/60 border-ps2-edge",
    header: "text-ps2-deep",
    bar: "bg-ps2-ink",
    dot: "bg-ps2-ink",
  },
};

export const CONFIDENCE = {
  high: {
    label: "High confidence",
    chip: "bg-vault-900 text-white border border-vault-900",
    note: "Corroborated across independent domains",
  },
  low: {
    label: "Low confidence",
    chip: "bg-white text-vault-600 border border-vault-200",
    note: "Single domain — treated cautiously",
  },
};

export const STATUS_LABELS = {
  new: "New",
  escalated: "Escalated",
  acknowledged: "Acknowledged",
  dismissed: "Dismissed",
};

export const fmtScore = (s) => (Math.round(s * 100) / 100).toFixed(2);

export const fmtTime = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};
