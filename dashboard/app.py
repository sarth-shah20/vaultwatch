"""VaultWatch analyst dashboard (Streamlit) — consumes the Correlation API.

Run:  streamlit run dashboard/app.py     (with the API up: uvicorn backend.app.main:app)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))  # allow `import client` when run by streamlit

import plotly.express as px
import streamlit as st

from client import (  # noqa: E402
    DECISION_COLOR,
    DEFAULT_BASE_URL,
    IncidentAPIClient,
    reasons_by_domain,
    summarize,
)

DOMAIN_LABEL = {"ps1_behavioral": "PS1 · behavioral (insider threat)",
                "ps2_transaction": "PS2 · transactional (fraud)"}

st.set_page_config(page_title="VaultWatch — Correlated Incidents", layout="wide")
st.title("VaultWatch — Correlated Incident Console")
st.caption("Fused PS1 (behavioral) + PS2 (transactional) risk → explained, risk-scored UnifiedIncidents.")

with st.sidebar:
    st.header("Connection")
    base_url = st.text_input("API base URL", value=DEFAULT_BASE_URL)
    status_filter = st.selectbox("Status", ["(all)", "new", "escalated", "acknowledged", "dismissed"])
    min_score = st.slider("Min combined score", 0.0, 1.0, 0.0, 0.05)
    st.button("Refresh")

client = IncidentAPIClient(base_url=base_url)

try:
    health = client.health()
except Exception as exc:
    st.error(f"Cannot reach the API at {base_url}. Start it with "
             f"`uvicorn backend.app.main:app` from the repo root.\n\n{exc}")
    st.stop()

incidents = client.list_incidents(
    status=None if status_filter == "(all)" else status_filter,
    min_score=min_score or None,
)
summary = summarize(incidents)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Incidents", summary["total"])
c2.metric("Revoke decisions", summary["revoke"])
c3.metric("High confidence", summary["by_confidence"].get("high", 0))
c4.metric("Suppressed entities", summary["suppressed"])

if summary["by_decision"]:
    fig = px.bar(
        x=list(summary["by_decision"].keys()), y=list(summary["by_decision"].values()),
        color=list(summary["by_decision"].keys()), color_discrete_map=DECISION_COLOR,
        labels={"x": "access decision", "y": "count"}, title="Incidents by access decision",
    )
    fig.update_layout(showlegend=False, height=280)
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Incidents")
if not incidents:
    st.info("No incidents match the current filters.")
    st.stop()

for inc in incidents:
    color = DECISION_COLOR.get(inc.get("access_decision"), "#888")
    label = (f"{inc['incident_id']} · {inc['entity_id']} · score {inc['combined_score']:.3f} · "
             f"{(inc.get('access_decision') or '').upper()} · {inc.get('confidence')}"
             + ("  ·  🔕 suppressed" if inc.get("suppressed") else ""))
    with st.expander(label):
        st.markdown(
            f"<span style='background:{color};color:white;padding:2px 8px;border-radius:4px'>"
            f"{(inc.get('access_decision') or '').upper()}</span> &nbsp; "
            f"status **{inc.get('status')}** · confidence **{inc.get('confidence')}** · "
            f"domains: {', '.join(inc.get('contributing_domains', []))}",
            unsafe_allow_html=True,
        )
        grouped = reasons_by_domain(inc)
        cols = st.columns(max(len(grouped), 1))
        for col, (domain, reasons) in zip(cols, grouped.items()):
            col.markdown(f"**{DOMAIN_LABEL.get(domain, domain)}**")
            for r in reasons:
                col.markdown(f"- `{r['signal_name']}` (w={r['weight']}) — {r['raw_value']}")

        st.markdown("**Analyst action**")
        reason = st.text_input("Reason (for dismiss)", key=f"reason-{inc['incident_id']}")
        a1, a2, a3 = st.columns(3)
        for label_btn, action, col in (("Acknowledge", "acknowledge", a1),
                                        ("Escalate", "escalate", a2),
                                        ("Dismiss", "dismiss", a3)):
            if col.button(label_btn, key=f"{action}-{inc['incident_id']}"):
                resp = client.send_feedback(inc["incident_id"], action, reason or None)
                if resp.status_code == 200:
                    st.success(f"{label_btn} applied — status now '{resp.json()['status']}'.")
                    st.rerun()
                else:
                    st.warning(f"{label_btn} rejected ({resp.status_code}): {resp.json().get('detail')}")
