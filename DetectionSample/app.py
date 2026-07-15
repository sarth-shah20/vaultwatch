import streamlit as st
import json
import plotly.express as px

st.set_page_config(page_title="Log Anomaly Dashboard", layout="wide")

def load_data():
    try:
        with open("anomaly_results.json") as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def main():
    st.title("Log Anomaly Detection Dashboard")

    data = load_data()
    if not data:
        st.warning("No anomaly data found. Run the anomaly detector script first.")
        return

    total = data["total_logs"]
    normal = data["normal_count"]
    anomalies = data["anomalies_count"]
    anomaly_logs = data["anomalies"]

    # Pie chart of normal vs anomalies
    pie_data = {
        "Status": ["Normal", "Anomalous"],
        "Count": [normal, anomalies]
    }

    fig = px.pie(pie_data, names="Status", values="Count", title="Logs Status Distribution",
                 color_discrete_map={"Normal":"green", "Anomalous":"red"})

    st.plotly_chart(fig, use_container_width=True)

    # Slideshow for anomaly logs
    st.header("Anomalous Logs")

    if anomalies == 0:
        st.info("No anomalies detected in current batch.")
    else:
        # Slider to browse anomalies
        idx = st.slider("Select anomaly log", 0, anomalies - 1, 0)

        selected = anomaly_logs[idx]
        st.markdown(f"**Log:** {selected['log']}")
        st.markdown(f"**Anomaly Score:** {selected['score']:.4f}")
        st.markdown(f"**Reason:** {selected['reason']}")

        # Button to go to next anomaly (manual refresh)
        if st.button("Next Anomaly"):
            idx = (idx + 1) % anomalies
            st.experimental_rerun()

if __name__ == "__main__":
    main()
