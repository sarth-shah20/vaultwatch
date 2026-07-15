import json
import os
import pandas as pd
import streamlit as st
import time


st.set_page_config(
    page_title="Bank of Maharashtra – Security Dashboard",

    layout="wide"
)

st.markdown(
    "<h1 style='text-align: center; color: navy;'>Bank of Maharashtra – Security Dashboard</h1>",
    unsafe_allow_html=True
)
st.markdown("---")


page = st.sidebar.radio("Navigate", ["Dashboard", "Chatbot"])


def load_anomaly_results(file_path="anomaly_results.json"):
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            data = json.load(f)
        return data
    else:
        return None

if page == "Dashboard":
    st.subheader("Real-time Anomaly Monitoring")

    data = load_anomaly_results()
    if data:

        col1, col2, col3 = st.columns(3)
        col1.metric("Total Logs Processed", data["total_logs"])
        col2.metric("Anomalies Detected", data["anomalies_count"])
        col3.metric("Last Update", time.strftime("%H:%M:%S"))

        st.markdown("### Detected Anomalies")

        if data["anomalies"]:
            anomalies_df = pd.DataFrame(data["anomalies"])
            st.dataframe(anomalies_df, use_container_width=True)
        else:
            st.success("No anomalies detected at the moment.")
    else:
        st.warning("No anomaly data found. Waiting for results...")


elif page == "Chatbot":
    st.subheader("Ask SecurityBot")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for role, text in st.session_state.chat_history:
        if role == "user":
            st.chat_message("user").markdown(text)
        else:
            st.chat_message("assistant").markdown(text)

    if user_input := st.chat_input("Type your message..."):
        st.session_state.chat_history.append(("user", user_input))
        bot_response = f" You asked: **{user_input}**\nI’ll process this and get back to you."
        st.session_state.chat_history.append(("assistant", bot_response))
        st.experimental_rerun()
