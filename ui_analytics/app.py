import os
import sys
import streamlit as st
import pandas as pd
import plotly.express as px
import duckdb

# Dynamically map parent path to safely invoke the agent state graph framework packages
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ai_orchestrator.agents.graph import run_monitored_agent

# Initialize connection to local persistent DuckDB analytical warehouse
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analytics_warehouse.db")

def init_duckdb_schema():
    """Context isolated method to safely construct infrastructure analytical tables."""
    # Use context manager to instantly release file lock upon completion
    with duckdb.connect(DB_FILE) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS system_logs (
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                query TEXT,
                routing_path TEXT,
                tokens_used INTEGER,
                latency_ms DOUBLE
            )
        """)

# Guarantee analytical components layer structures are available
init_duckdb_schema()

# ==========================================
# STREAMLIT PAGE CONFIGURATION & LAYOUT
# ==========================================
st.set_page_config(page_title="NexusAI Ops Center", layout="wide", page_icon="📊")

st.title("NexusAI Operations & Analytics Control Plane")
st.markdown("---")

# Split operational user actions from big-data system dashboards
col_ui, col_analytics = st.columns([1, 1.2])

# ==========================================
# LEFT PANEL: ENTERPRISE INTERACTION NODE
# ==========================================
with col_ui:
    st.subheader("Enterprise AI Interaction Node")

    # Input options: Text query or simulated audio input file
    input_mode = st.radio("Select Input Modality:", ["Text Console", "Simulated Audio Log Frame"])

    if input_mode == "Text Console":
        user_query = st.text_input("Enter Enterprise Query:", value="What are our rules about destructive database writes?")
    else:
        st.info("Simulating speech-to-text translation pipeline via core ingestion engine...")
        selected_option = st.selectbox("Select Cached Audio Log Ingestion:", [
            "AUDIO_LOG_2026_09_24_001: Querying data storage container configurations",
            "AUDIO_LOG_2026_09_24_002: Check safety gates for autonomous tool execution"
        ])
        user_query = selected_option.split(": ")[-1]

    if st.button("⚡ Execute Workflow Pipeline"):
        with st.spinner("Orchestrating agents and retrieving local context patterns..."):
            # Trigger our LangGraph state machine running MLflow traces under the hood
            result = run_monitored_agent(user_query)

            dest_node = result.get("routing_destination", "COMPLEX_REASONING")
            tokens = result.get("tokens_used", 0)

            # Commit transactional metrics immediately inside an isolated write hook context
            with duckdb.connect(DB_FILE) as con:
                con.execute("""
                    INSERT INTO system_logs (query, routing_path, tokens_used, latency_ms)
                    VALUES (?, ?, ?, ?)
                """, (user_query, dest_node, int(tokens), 245.50))

            # Display localized outputs
            st.success("Analysis Complete!")
            st.markdown(f"**Security Check Status:** {'Passed' if result.get('security_passed', True) else 'Triggered Shield'}")
            st.markdown(f"**Identified Routing Node Path:** `{dest_node}`")

            st.subheader("Cloud Core Brain Resolution (Claude 4.5 Haiku):")
            st.info(result.get("final_response", "No agent resolution returned."))

# ==========================================
# 📊 RIGHT PANEL: SPARK METRICS & BI GRAPHS
# ==========================================
with col_analytics:
    st.subheader("Real-Time Platform Analytics (Local DuckDB BI Layer)")

    # Execute dynamic queries using self-closing file locks to protect pipeline updates
    with duckdb.connect(DB_FILE) as con:
        df_logs = con.execute("SELECT * FROM system_logs ORDER BY timestamp DESC").df()
        try:
            df_spark = con.execute("SELECT * FROM platform_summary_metrics ORDER BY run_timestamp DESC LIMIT 1").df()
        except Exception:
            df_spark = pd.DataFrame()

    if df_logs.empty:
        st.warning("No transactional telemetry tracks found inside analytical layers. Execute an agent workflow above to generate charts.")
    else:
        # High level system KPI display boxes
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric(label="Total Executed Actions", value=len(df_logs))
        kpi2.metric(label="Total Spent Tokens", value=int(df_logs['tokens_used'].sum()))

        # Display the aggregated Spark calculations dynamically if data exists
        if not df_spark.empty:
            batch_count = int(df_spark['total_records_analyzed'].iloc[0])
            err_ratio = float(df_spark['calculated_error_ratio'].iloc[0]) * 100
            kpi3.metric(label="Spark Batch Records", value=batch_count, delta=f"{err_ratio:.1f}% System Err Rate", delta_color="inverse")
        else:
            kpi3.metric(label="Spark Status", value="Offline", delta="Run etl_spark_job.py")

        st.markdown("---")

        # Interactive Graph 1: Token expenditures over time
        st.write("**Token Consumption Trends Over Operations**")
        fig_tokens = px.line(df_logs, x='timestamp', y='tokens_used', title="API Call Cost Tracing (Anthropic Budget Monitoring)")
        st.plotly_chart(fig_tokens, width='stretch')

        # Interactive Graph 2: Intent path distribution breakdown
        st.write("🗺️ **Multi-Agent Intent Class Distribution**")
        fig_pie = px.pie(df_logs, names='routing_path', title="Orchestrator Routing Decision Breakdown", hole=0.3)
        st.plotly_chart(fig_pie, width='stretch')
