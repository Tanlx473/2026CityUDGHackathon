from __future__ import annotations

import time

import requests
import streamlit as st


API_BASE = st.sidebar.text_input("Backend URL", value="http://127.0.0.1:8000")


def api_request(method: str, path: str, **kwargs):
    try:
        response = requests.request(method, f"{API_BASE}{path}", timeout=20, **kwargs)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        st.error(f"Backend service cannot be reached or returned an error: {exc}")
        return None


st.set_page_config(page_title="AI Agent Development Pipeline Control Panel", layout="wide")
st.title("AI Agent Development Pipeline Control Panel")

if "batch_id" not in st.session_state:
    st.session_state.batch_id = ""

with st.form("create_batch"):
    uploaded = st.file_uploader("Upload Markdown product specification", type=["md"])
    mode = st.selectbox("Running mode", ["auto", "manual"])
    submitted = st.form_submit_button("Start batch")
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
                st.success(f"Batch created: {batch_id}")

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
        st.subheader("Node status")
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
