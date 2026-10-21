"""NexusAI operations dashboard (Streamlit).

Every question goes through the Java gateway with an API key, so the dashboard is subject to
the same RBAC and audit ledger as any other client. Read-only data sources:

* live request events   data/events/*.jsonl        (queried in place with DuckDB, no locks)
* batch analytics       data/warehouse/analytics.duckdb (rebuilt by the pipeline, atomic swap)
* evaluation reports    reports/eval_*.json
* audit ledger          GET /api/v1/audit           (ADMIN key only)
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

import duckdb
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv("NEXUS_DATA_DIR", ROOT / "data"))
REPORTS = Path(os.getenv("NEXUS_REPORTS_DIR", ROOT / "reports"))
GATEWAY = os.getenv("NEXUS_GATEWAY_URL", "http://localhost:8080").rstrip("/")
KEYS = {"Analyst": os.getenv("NEXUS_ANALYST_API_KEY", ""), "Admin": os.getenv("NEXUS_ADMIN_API_KEY", "")}
MLFLOW_UI = os.getenv("NEXUS_MLFLOW_UI_URL", "http://localhost:5001")

st.set_page_config(page_title="NexusAI Operations", layout="wide", page_icon="🛰️")

# ---------------------------------------------------------------- colours (reference palette, by mode)
DARK = (st.context.theme.type or "light") == "dark"
SERIES = ["#3987e5", "#d95926", "#199e70"] if DARK else ["#2a78d6", "#eb6834", "#1baf7a"]
TEXT_2 = "#c3c2b7" if DARK else "#52514e"
GRID = "#383835" if DARK else "#e7e6e2"
CRITICAL = "#d03b3b"
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
if DARK:  # low values recede into the surface: dark-to-light on a dark background
    BLUE_RAMP = BLUE_RAMP[::-1]


def styled(fig: go.Figure, title: str, y_title: str = "", height: int = 300) -> go.Figure:
    fig.update_layout(title={"text": title, "font": {"size": 15}}, height=height,
                      margin={"l": 8, "r": 8, "t": 44, "b": 8},
                      legend={"orientation": "h", "y": 1.12, "x": 1, "xanchor": "right"}, hovermode="x unified",
                      bargap=0.35, font={"color": TEXT_2})
    fig.update_xaxes(showgrid=False, linecolor=GRID)
    fig.update_yaxes(title=y_title, gridcolor=GRID, zeroline=False, rangemode="tozero")
    return fig


def show(fig: go.Figure, table: pd.DataFrame | None = None) -> None:
    st.plotly_chart(fig, width="stretch", theme="streamlit")
    if table is not None:
        with st.expander("Data table"):
            st.dataframe(table, hide_index=True, width="stretch")


# ---------------------------------------------------------------- data access
@st.cache_data(ttl=5)
def load_events() -> pd.DataFrame:
    files = sorted((DATA / "events").glob("*.jsonl"))
    if not files:
        return pd.DataFrame()
    df = duckdb.execute("SELECT * FROM read_json_auto(?, union_by_name=true)", [[str(f) for f in files]]).df()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values("ts")


@st.cache_data(ttl=60)
def load_warehouse(table: str) -> pd.DataFrame:
    path = DATA / "warehouse" / "analytics.duckdb"
    if not path.exists():
        return pd.DataFrame()
    with duckdb.connect(str(path), read_only=True) as con:  # short-lived: the pipeline swaps the file
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if table not in tables:  # whitelist: only existing tables, so the f-string below is safe
            return pd.DataFrame()
        return con.execute(f"SELECT * FROM {table}").df()  # noqa: S608


@st.cache_data(ttl=30)
def load_reports() -> dict[str, dict]:
    return {p.stem.removeprefix("eval_"): json.loads(p.read_text()) for p in sorted(REPORTS.glob("eval_*.json"))}


def gateway(method: str, path: str, persona: str, **kwargs) -> tuple[int, dict | list]:
    key = KEYS.get(persona, "")
    if not key:
        return 0, {"error": f"No API key configured for {persona} (set NEXUS_{persona.upper()}_API_KEY)"}
    try:
        r = requests.request(method, f"{GATEWAY}{path}", headers={"X-API-Key": key}, timeout=160, **kwargs)
        return r.status_code, r.json()
    except requests.RequestException as exc:
        return 0, {"error": f"Gateway unreachable at {GATEWAY}: {exc}"}
    except ValueError:
        return r.status_code, {"error": r.text[:300]}


def log_feedback(trace_id: str, helpful: bool) -> str:
    try:
        import mlflow
        from mlflow.entities import AssessmentSource

        mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001"))
        mlflow.log_feedback(trace_id=trace_id, name="user_helpful", value=helpful,
                            source=AssessmentSource(source_type="HUMAN", source_id="dashboard"))
        return "Thanks - feedback attached to the MLflow trace."
    except Exception as exc:  # MLflow down: feedback is optional
        return f"Could not record feedback ({exc})."


# ---------------------------------------------------------------- page
st.title("NexusAI Operations")
st.caption(f"Gateway {GATEWAY} · data {DATA} · [MLflow]({MLFLOW_UI})")
tab_ask, tab_voice, tab_ops, tab_batch, tab_quality, tab_audit = st.tabs(
    ["Ask", "Voice", "Live operations", "Pipeline analytics", "Model quality", "Audit ledger"])

with tab_ask:
    st.session_state.setdefault("session_id", f"ui-{uuid.uuid4().hex[:8]}")
    left, right = st.columns([1, 1.3])
    with left:
        persona = st.radio("Call the gateway as", ["Analyst", "Admin"], horizontal=True,
                           help="Each persona uses its own API key; the gateway decides what the role may do.")
        user_id = st.selectbox("Personalise tool recommendations for user",
                               ["(none)"] + [f"u{i:03d}" for i in range(80)], index=2)
        question = st.text_area("Question", "Who has to approve destructive database writes made by an AI agent?",
                                height=110)
        st.caption(f"Session `{st.session_state.session_id}` - follow-up questions share conversation memory.")
        asked = st.button("Ask", type="primary")
    with right:
        if asked and question.strip():
            body = {"query": question.strip(), "sessionId": st.session_state.session_id}
            if user_id != "(none)":
                body["userId"] = user_id
            with st.spinner("Routing, retrieving and answering..."):
                code, reply = gateway("POST", "/api/v1/query", persona, json=body)
            st.session_state.last_reply = (code, reply)
        if "last_reply" in st.session_state:
            code, r = st.session_state.last_reply
            if code != 200:
                st.error(f"HTTP {code}: {r.get('error') or r.get('errors') or r.get('status')}")
            else:
                if r["status"] == "BLOCKED":
                    st.warning(f"🛡️ Blocked by the {r['security']['layer']} layer ({r['security']['category']})")
                st.markdown(r["answer"])
                route = r.get("route") or {}
                usage = r.get("usage") or {}
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Route", route.get("intent", "-"), route.get("source"), delta_color="off")
                c2.metric("Model", usage.get("model") or "-", usage.get("provider"), delta_color="off")
                c3.metric("Tokens in/out", f"{usage.get('input_tokens', 0)}/{usage.get('output_tokens', 0)}")
                c4.metric("Latency", f"{r.get('gateway_latency_ms', r.get('latency_ms', 0)) / 1000:.1f} s",
                          f"${usage.get('cost_usd', 0):.4f}", delta_color="off")
                if r.get("sources"):
                    st.markdown("**Sources:** " + ", ".join(f"`{s['source']}`" for s in r["sources"]))
                if r.get("recommendations"):
                    st.dataframe(pd.DataFrame(r["recommendations"])[["id", "score", "relevance", "affinity", "reason"]],
                                 hide_index=True, width="stretch")
                pii = (r.get("security") or {}).get("pii_redacted") or {}
                if pii:
                    st.info("Redacted before any model saw it: " + ", ".join(f"{v}× {k}" for k, v in pii.items()))
                if r.get("trace_id"):
                    f1, f2, _ = st.columns([1, 1, 4])
                    if f1.button("👍 Helpful"):
                        st.toast(log_feedback(r["trace_id"], True))
                    if f2.button("👎 Not helpful"):
                        st.toast(log_feedback(r["trace_id"], False))
                with st.expander("Raw response"):
                    st.json(r)

with tab_voice:
    st.markdown("Upload a 16-bit PCM WAV. The C++ ingestion service watches `data/audio_inbox`, detects speech, "
                "transcribes it with whisper.cpp and submits the transcript to the gateway as the "
                "`audio-ingest` client.")
    upload = st.file_uploader("WAV file", type=["wav"])
    if upload is not None and st.button("Queue for transcription"):
        inbox = DATA / "audio_inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(upload.name).name)
        (inbox / f"{uuid.uuid4().hex[:6]}_{safe}").write_bytes(upload.getvalue())
        st.success("Queued. Results appear below within a few seconds.")
    results = []
    for folder in ("audio_processed", "audio_failed"):
        for p in sorted((DATA / folder).glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
            item = json.loads(p.read_text())
            reply = item.get("gateway_reply") or {}
            results.append({"file": item["file"], "transcript": item.get("transcript"), "speech %": round(
                100 * item.get("speech_ratio", 0)), "stt ms": item.get("stt_ms"), "status": reply.get("status") or
                item.get("error"), "answer": (reply.get("answer") or "")[:160]})
    if results:
        st.dataframe(pd.DataFrame(results), hide_index=True, width="stretch")
    else:
        st.caption("No processed audio yet.")


@st.fragment(run_every="10s")
def live_operations() -> None:
    ev = load_events()
    if ev.empty:
        st.info("No requests yet - ask something in the Ask tab.")
        return
    answered = ev[ev["status"] == "OK"]
    local_share = (answered["llm_provider"] != "anthropic").mean() if len(answered) else 0
    k = st.columns(6)
    k[0].metric("Requests", f"{len(ev):,}")
    k[1].metric("p50 latency", f"{ev['latency_ms'].quantile(0.5) / 1000:.1f} s")
    k[2].metric("p95 latency", f"{ev['latency_ms'].quantile(0.95) / 1000:.1f} s")
    k[3].metric("Blocked", f"{(ev['status'] == 'BLOCKED').mean():.0%}")
    k[4].metric("Answered locally", f"{local_share:.0%}",
                help="Share of answers produced by local models (no API cost)")
    k[5].metric("Cloud spend", f"${ev['llm_cost_usd'].fillna(0).sum():.4f}")

    span = ev["ts"].max() - ev["ts"].min()
    freq = "1min" if span < pd.Timedelta(hours=2) else "10min" if span < pd.Timedelta(days=2) else "1h"
    bucket = ev.set_index("ts").resample(freq)
    per = pd.DataFrame({"requests": bucket.size(), "p50": bucket["latency_ms"].quantile(0.5) / 1000,
                        "p95": bucket["latency_ms"].quantile(0.95) / 1000}).reset_index().dropna()
    if len(per) < 2:
        st.caption("Time-series charts appear once requests span more than one time bucket.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            fig = go.Figure(go.Bar(x=per["ts"], y=per["requests"], marker_color=SERIES[0], name="requests",
                                   width=pd.Timedelta(freq).total_seconds() * 1000 * 0.8,
                                   hovertemplate="%{x|%H:%M}: %{y} requests<extra></extra>"))
            show(styled(fig, f"Requests per {freq}", "requests").update_xaxes(tickformat="%b %d %H:%M"),
                 per[["ts", "requests"]])
        with c2:
            fig = go.Figure()
            for i, col in enumerate(["p50", "p95"]):
                fig.add_trace(go.Scatter(x=per["ts"], y=per[col], mode="lines+markers", name=col, line={"width": 2},
                                         marker={"size": 8, "color": SERIES[i]}, line_color=SERIES[i],
                                         hovertemplate=f"{col} %{{y:.1f}} s<extra></extra>"))
            show(styled(fig, f"Latency per {freq}", "seconds").update_xaxes(tickformat="%b %d %H:%M"),
                 per[["ts", "p50", "p95"]].round(2))

    c3, c4 = st.columns(2)
    with c3:
        routes = ev.assign(route=ev["route"].fillna("BLOCKED")).groupby("route").size().sort_values()
        fig = go.Figure(go.Bar(x=routes.values, y=routes.index, orientation="h", marker_color=SERIES[0],
                               hovertemplate="%{y}: %{x} requests<extra></extra>"))
        show(styled(fig, "Requests by route", height=260).update_layout(hovermode="closest"),
             routes.rename("requests").reset_index())
    with c4:
        by_model = (answered.assign(model=answered["llm_model"].fillna("-"))
                    .groupby("model").agg(requests=("request_id", "size"), tokens=("llm_input_tokens", "sum"),
                                          cost_usd=("llm_cost_usd", "sum")).sort_values("requests"))
        fig = go.Figure(go.Bar(x=by_model["requests"], y=by_model.index, orientation="h", marker_color=SERIES[0],
                               customdata=by_model["cost_usd"],
                               hovertemplate="%{y}: %{x} answers, $%{customdata:.4f}<extra></extra>"))
        show(styled(fig, "Answers by model (hover for cost)", height=260).update_layout(hovermode="closest"),
             by_model.reset_index())
    st.markdown("**Latest requests** (redacted text only)")
    cols = ["ts", "principal", "source", "status", "route", "route_source", "llm_model", "latency_ms", "query"]
    st.dataframe(ev[[c for c in cols if c in ev]].tail(25).iloc[::-1], hide_index=True, width="stretch")


with tab_ops:
    live_operations()

with tab_batch:
    hourly = load_warehouse("log_errors_hourly")
    if hourly.empty:
        st.info("Warehouse not built yet - run `make pipeline`.")
    else:
        runs = load_warehouse("pipeline_runs")
        if not runs.empty:
            run = runs.iloc[-1]
            checks = json.loads(run["dq"]) if isinstance(run["dq"], str) else run["dq"]
            cols = st.columns(len(checks) + 1)
            cols[0].metric("Log rows in lake", f"{int(run['log_rows']):,}")
            for col, (name, check) in zip(cols[1:], checks.items(), strict=True):
                col.metric(name.replace("_", " "), "✅ pass" if check["ok"] else "❌ fail")
        pivot = hourly.pivot_table(index="component", columns="hour", values="error_rate").sort_index()
        incidents = load_warehouse("incident_hours")
        fig = go.Figure(go.Heatmap(z=pivot.values, x=pivot.columns, y=pivot.index, zmin=0,
                                   colorscale=[[i / (len(BLUE_RAMP) - 1), c] for i, c in enumerate(BLUE_RAMP)],
                                   colorbar={"title": "error rate", "tickformat": ".0%"}, ygap=2,
                                   hovertemplate="%{y}<br>%{x}<br>error rate %{z:.1%}<extra></extra>"))
        if not incidents.empty:
            fig.add_trace(go.Scatter(x=incidents["hour"], y=incidents["component"], mode="markers",
                                     name="⚠ incident hour (error rate ≥ 4× component baseline)", showlegend=True,
                                     marker={"symbol": "square-open", "size": 16, "color": CRITICAL,
                                             "line": {"width": 2.5}},
                                     customdata=incidents[["error_rate", "baseline"]],
                                     hovertemplate="%{y} incident<br>%{x}<br>error rate %{customdata[0]:.1%} "
                                                   "(baseline %{customdata[1]:.1%})<extra></extra>"))
        show(styled(fig, "Hourly error rate by component (incidents flagged by Spark)", height=380)
             .update_layout(hovermode="closest"), incidents if not incidents.empty else None)
        pii = load_warehouse("pii_summary").sort_values("redactions")
        if not pii.empty:
            fig = go.Figure(go.Bar(x=pii["redactions"], y=pii["pii_type"], orientation="h", marker_color=SERIES[0],
                                   customdata=pii["stage"],
                                   hovertemplate="%{y}: %{x:,} (%{customdata})<extra></extra>"))
            show(styled(fig, "PII redactions by type", height=320).update_layout(hovermode="closest"), pii)
        daily = load_warehouse("agent_daily")
        if not daily.empty:
            st.markdown("**Agent requests by day, route and provider** (batch mart)")
            st.dataframe(daily, hide_index=True, width="stretch")

with tab_quality:
    reports = load_reports()
    if not reports:
        st.info("No evaluation reports yet - run `make eval`.")
    else:
        rows = []
        for profile, rep in reports.items():
            for suite, res in rep["results"].items():
                for metric, value in res["metrics"].items():
                    if isinstance(value, int | float) and not isinstance(value, bool):
                        rows.append({"profile": profile, "suite": suite, "metric": metric, "value": value})
        table = pd.DataFrame(rows).pivot_table(index=["suite", "metric"], columns="profile", values="value")
        gates = {p: "✅ pass" if not r["gate_failures"] else "❌ " + "; ".join(r["gate_failures"])
                 for p, r in reports.items()}
        st.markdown("  \n".join(f"**{p}** gate: {g} · {reports[p]['created_at']}" for p, g in gates.items()))
        st.dataframe(table.round(4), width="stretch", height=560)
        st.caption(f"Per-case results and traces: [MLflow experiment nexus-evals]({MLFLOW_UI})")

with tab_audit:
    st.markdown("The ledger is append-only (a database trigger rejects UPDATE, DELETE and TRUNCATE) and stores a "
                "SHA-256 hash of each query, never the text. Only the **Admin** key may read it.")
    persona_audit = st.radio("Read the ledger as", ["Admin", "Analyst"], horizontal=True, key="audit_persona")
    code, data = gateway("GET", "/api/v1/audit?limit=100", persona_audit)
    if code == 200:
        st.dataframe(pd.DataFrame(data), hide_index=True, width="stretch")
    else:
        st.error(f"HTTP {code}: {data.get('error') if isinstance(data, dict) else data}")
