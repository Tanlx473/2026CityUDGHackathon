from __future__ import annotations

import time

import requests
import streamlit as st


st.set_page_config(page_title="AI Agent Development Pipeline Control Panel", layout="wide")

API_BASE = st.sidebar.text_input("Backend URL", value="http://127.0.0.1:8000")
REQUEST_TIMEOUT_SECONDS = st.sidebar.number_input(
    "Request timeout (seconds)",
    min_value=20,
    max_value=300,
    value=120,
    step=10,
)

STATUS_EMOJI = {
    "queued": "⏳",
    "running": "⚙️",
    "succeeded": "✅",
    "failed": "❌",
    "paused": "⏸️",
}


def api_request(method: str, path: str, **kwargs):
    timeout = kwargs.pop("timeout", REQUEST_TIMEOUT_SECONDS)
    try:
        response = requests.request(method, f"{API_BASE}{path}", timeout=timeout, **kwargs)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        st.error(f"Backend service cannot be reached or returned an error: {exc}")
        return None


st.title("AI Agent Development Pipeline Control Panel")

if "batch_id" not in st.session_state:
    st.session_state.batch_id = ""

with st.form("create_batch"):
    uploaded = st.file_uploader("Upload Markdown product specification", type=["md"])
    mode = st.selectbox(
        "Running mode",
        ["auto", "manual"],
        help="auto: all nodes run in sequence without interruption. manual: pipeline pauses after each node for your approval.",
    )
    submitted = st.form_submit_button("Create batch")
    if submitted:
        if uploaded is None:
            st.warning("Please upload a Markdown file.")
        else:
            files = {"file": (uploaded.name, uploaded.getvalue(), "text/markdown")}
            response = api_request("POST", "/api/v1/batches", files=files, data={"mode": mode})
            if response is not None:
                batch_id = response.json()["batch_id"]
                st.session_state.batch_id = batch_id
                if mode == "auto":
                    api_request("POST", f"/api/v1/batches/{batch_id}/run")
                    st.success(f"Batch created and pipeline started automatically: {batch_id}")
                else:
                    st.success(f"Batch created in manual mode: {batch_id}. Use the controls below to run each node.")

batch_id = st.text_input("Current batch_id", value=st.session_state.batch_id)
if batch_id:
    st.session_state.batch_id = batch_id

col_a, col_b = st.columns([1, 1])
with col_a:
    if st.button("Refresh status", disabled=not batch_id):
        st.rerun()
with col_b:
    if st.button("Run auto pipeline", disabled=not batch_id):
        api_request("POST", f"/api/v1/batches/{batch_id}/run")
        time.sleep(1)
        st.rerun()

if batch_id:
    state_response = api_request("GET", f"/api/v1/batches/{batch_id}")
    if state_response is not None:
        state = state_response.json()
        batch_status = state.get("status", "")
        batch_mode = state.get("mode", "auto")
        current_node = state.get("current_node")

        # ── Manual mode control panel ──────────────────────────────────────
        if batch_mode == "manual":
            st.divider()
            st.subheader("Manual Mode Controls")

            node_labels = {"design": "Design", "code": "Code", "test": "Test"}
            step_cols = st.columns(3)
            for idx, nid in enumerate(["design", "code", "test"]):
                node_status = state["nodes"][nid]["status"]
                emoji = STATUS_EMOJI.get(node_status, "")
                with step_cols[idx]:
                    st.metric(label=node_labels[nid], value=f"{emoji} {node_status}")

            if batch_status == "queued":
                st.info("Pipeline not started yet.")
                if st.button("▶ Start — run design node"):
                    api_request("POST", f"/api/v1/batches/{batch_id}/run")
                    time.sleep(1)
                    st.rerun()

            elif batch_status == "paused":
                st.warning(f"⏸️ Pipeline paused. Waiting for your approval to run: **{current_node}**")
                if st.button(f"▶ Approve & run {current_node}"):
                    api_request("POST", f"/api/v1/batches/{batch_id}/advance")
                    time.sleep(1)
                    st.rerun()

            elif batch_status == "running":
                st.info(f"⚙️ Running node: **{current_node}** — refresh to check progress.")

            elif batch_status == "succeeded":
                st.success("✅ All nodes completed successfully.")

            elif batch_status == "failed":
                st.error(f"❌ Pipeline failed at node: **{current_node}**. Use Retry below.")

            st.divider()

        # ── Node status table ──────────────────────────────────────────────
        batch_emoji = STATUS_EMOJI.get(batch_status, "")
        st.subheader(f"Batch status: {batch_emoji} {batch_status}  |  Mode: {batch_mode}")
        rows = []
        for node in state["nodes"].values():
            rows.append(
                {
                    "node_id": node["node_id"],
                    "status": node["status"],
                    "retries": node["retries"],
                    "started_at": node["started_at"],
                    "finished_at": node["finished_at"],
                    "error_message": node["error_message"],
                }
            )
        st.dataframe(rows, use_container_width=True)

        retry_cols = st.columns(3)
        for index, node_id in enumerate(["design", "code", "test"]):
            with retry_cols[index]:
                if st.button(f"Retry {node_id}"):
                    api_request("POST", f"/api/v1/batches/{batch_id}/retry/{node_id}")
                    time.sleep(1)
                    st.rerun()

    log_response = api_request("GET", f"/api/v1/batches/{batch_id}/logs")
    if log_response is not None:
        st.subheader("Execution log")
        st.dataframe(log_response.json(), use_container_width=True)

    artifacts_response = api_request("GET", f"/api/v1/batches/{batch_id}/artifacts")
    if artifacts_response is not None:
        artifacts = artifacts_response.json()
        if state_response is not None and state_response.json().get("status") == "succeeded":
            pkg = api_request("GET", f"/api/v1/batches/{batch_id}/package")
            if pkg is not None:
                st.download_button(
                    label="⬇️ Download generated code (.zip)",
                    data=pkg.content,
                    file_name=f"{batch_id}.zip",
                    mime="application/zip",
                    type="primary",
                    use_container_width=True,
                )
            st.divider()

        st.subheader("Artifact list")
        st.dataframe(artifacts, use_container_width=True)

        st.subheader("Artifact downloads")
        preferred = ["overview_design.md", "design_manifest.json", "code_manifest.json", "test_plan.md"]
        for artifact in artifacts:
            name = artifact["path"].split("/")[-1]
            if name in preferred:
                download_response = api_request("GET", f"/api/v1/batches/{batch_id}/download", params={"path": artifact["path"]})
                if download_response is not None:
                    st.download_button(
                        label=f"Download {name}",
                        data=download_response.content,
                        file_name=name,
                        mime="application/octet-stream",
                    )
