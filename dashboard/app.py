"""Umuhinzi AI - Streamlit demo dashboard.

Run from the project folder:

    streamlit run dashboard/app.py

The dashboard talks to the FastAPI backend over HTTP. It never sees the
Sunbird token: speech recognition and speech synthesis happen on the backend.
"""

from __future__ import annotations

import os

import requests
import streamlit as st

DEFAULT_API_URL = os.getenv("UMUHINZI_API_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(
    page_title="Umuhinzi AI demo",
    page_icon="🌱",
    layout="wide",
)

st.title("Umuhinzi AI")
st.caption(
    "Voice-first crop pest assistant for smallholder farmers in Rwanda. "
    "Demo dashboard - works with the mock ASR, no phone needed."
)


def check_backend(api_url: str) -> None:
    """Show whether the backend is reachable and which ASR backend is active."""
    try:
        response = requests.get(f"{api_url}/health", timeout=5)
        response.raise_for_status()
        health = response.json()
    except (requests.RequestException, ValueError) as exc:
        st.error(f"Cannot reach the backend at {api_url}: {exc}")
        st.code("uvicorn app.main:app --reload", language="powershell")
        return

    st.success(
        f"Backend connected. ASR backend: **{health.get('asr_backend', 'unknown')}**, "
        f"TTS backend: **{health.get('tts_backend', 'unknown')}**"
    )
    if health.get("asr_backend") == "sunbird" and not health.get(
        "sunbird_configured"
    ):
        st.warning(
            "ASR_BACKEND=sunbird but SUNBIRD_API_TOKEN is empty in `.env`. "
            "Requests will fall back to mock (asking the farmer to repeat)."
        )
    if health.get("tts_backend") == "sunbird" and not health.get(
        "sunbird_configured"
    ):
        st.warning(
            "TTS_BACKEND=sunbird but SUNBIRD_API_TOKEN is empty in `.env`. "
            "No audio player will be shown."
        )


@st.cache_data(show_spinner=False)
def fetch_tts(api_url: str, text: str) -> tuple[bytes, str] | None:
    """Ask the backend to speak the Kinyarwanda reply; None means no audio."""
    try:
        response = requests.post(f"{api_url}/tts", json={"text": text}, timeout=60)
        response.raise_for_status()
    except requests.RequestException:
        return None

    if response.headers.get("X-Audio-Available") == "0" or not response.content:
        return None
    content_type = (
        response.headers.get("Content-Type", "").split(";")[0].strip() or "audio/wav"
    )
    return response.content, content_type


def show_result(api_url: str, payload: dict) -> None:
    """Render transcription, diagnosis, audio and the Kinyarwanda reply."""
    st.subheader("Transcription")
    transcription = payload.get("transcription") or ""
    if transcription:
        st.write(transcription)
    else:
        st.warning("No speech was recognised.")

    diagnosis = payload.get("diagnosis")
    if diagnosis:
        st.subheader("Diagnosis")
        col1, col2 = st.columns(2)
        col1.metric("Pest (Kinyarwanda)", diagnosis.get("name_rw") or "-")
        col2.metric(
            "Confidence",
            f"{float(diagnosis.get('confidence', 0)):.0%}",
        )
        st.write(
            f"**English:** {diagnosis.get('name_en') or '-'}  \n"
            f"**Method:** {diagnosis.get('method') or '-'}"
        )

    reply = payload.get("reply_rw") or ""
    with st.spinner("Preparing audio..."):
        spoken = fetch_tts(api_url, reply) if reply else None

    st.subheader("Reply played to the farmer")
    st.info(reply or "(no reply)")
    if spoken is not None:
        audio_bytes, content_type = spoken
        st.audio(audio_bytes, format=content_type)
    elif reply:
        st.caption("TTS audio unavailable (mock backend or Sunbird error).")

    with st.expander("Raw JSON (for debugging)"):
        st.json(payload)


def post_audio(api_url: str, uploaded) -> dict:
    """Send an uploaded/recorded file to the backend `/asr` endpoint."""
    # Streamlit's file_uploader and audio_input both expose getvalue(); keep a
    # read() fallback for other uploaded-file-like objects.
    if hasattr(uploaded, "getvalue"):
        audio_bytes = uploaded.getvalue()
    else:
        audio_bytes = uploaded.read()

    filename = getattr(uploaded, "name", None) or "recording.wav"
    content_type = getattr(uploaded, "type", None) or "audio/wav"

    response = requests.post(
        f"{api_url}/asr",
        files={"audio": (filename, audio_bytes, content_type)},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


with st.sidebar:
    st.header("Backend")
    api_url = st.text_input("FastAPI URL", value=DEFAULT_API_URL).rstrip("/")

    if st.button("Check connection"):
        check_backend(api_url)

    st.markdown(
        "Start the backend in another terminal:\n\n"
        "```powershell\nuvicorn app.main:app --reload\n```"
    )
    st.markdown(
        "The Sunbird token stays on the backend (`SUNBIRD_API_TOKEN` in `.env`)."
    )

audio_tab, text_tab = st.tabs(["Audio / microphone", "Text demo"])

with audio_tab:
    st.subheader("Upload a recording")
    uploaded_file = st.file_uploader(
        "Choose an audio file (WAV, MP3, M4A, OGG, ...)",
        type=["wav", "mp3", "m4a", "ogg", "aac", "flac", "webm", "amr"],
    )
    if uploaded_file is not None:
        st.audio(uploaded_file)

    st.subheader("Or record with your microphone")
    try:
        recorded_audio = st.audio_input(
            "Record the farmer's symptom description (Kinyarwanda)"
        )
    except AttributeError:
        recorded_audio = None
        st.info("Microphone recording needs Streamlit 1.38 or newer.")

    if recorded_audio is not None:
        st.audio(recorded_audio)

    # Prefer the microphone recording when both are present.
    audio_source = recorded_audio if recorded_audio is not None else uploaded_file

    if audio_source is None:
        st.caption("Upload a file or record audio to begin.")
    elif st.button("Transcribe and diagnose", type="primary"):
        with st.spinner("Sending audio to the backend..."):
            try:
                result = post_audio(api_url, audio_source)
            except requests.RequestException as exc:
                st.error(f"Backend request failed: {exc}")
            except ValueError:
                st.error("The backend returned an invalid response.")
            else:
                show_result(api_url, result)

with text_tab:
    st.subheader("Type a symptom description")
    st.caption(
        "Useful when testing without audio. Example: "
        "amababi y'ibigori arashye kandi afite uduhumbi"
    )
    text = st.text_area(
        "Symptoms",
        value="amababi y'ibigori arashye kandi afite uduhumbi",
        height=100,
    )

    location_col, district_col = st.columns(2)
    sector = location_col.text_input(
        "Sector (for outbreak tracking)",
        value="Kacyiru",
        help="Reports of the same pest in one sector can trigger an outbreak alert.",
    )
    district = district_col.text_input("District", value="Gasabo")

    if st.button("Diagnose text"):
        try:
            response = requests.post(
                f"{api_url}/diagnose",
                json={
                    "text": text,
                    "sector": sector,
                    "district": district,
                    "session_id": "dashboard",
                },
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as exc:
            st.error(f"Backend request failed: {exc}")
        except ValueError:
            st.error("The backend returned an invalid response.")
        else:
            show_result(
                api_url,
                {
                    "transcription": result.get("input", text),
                    "diagnosis": result.get("diagnosis"),
                    "reply_rw": result.get("reply_rw"),
                }
            )
            if result.get("outbreak_alert"):
                st.warning(result["outbreak_alert"]["message_rw"])

st.divider()
st.subheader("Active outbreak alerts")
try:
    alert_response = requests.get(
        f"{api_url}/alerts",
        params={"active_only": True},
        timeout=5,
    )
    alert_response.raise_for_status()
    active_alerts = alert_response.json().get("alerts", [])
except (requests.RequestException, ValueError):
    st.info("Start the backend to see outbreak alerts.")
else:
    if not active_alerts:
        st.success("No active outbreak alerts.")
    else:
        for alert in active_alerts:
            st.warning(alert.get("message_rw") or "(no message)")
            st.caption(
                f"Pest: {alert.get('pest_id')} | Sector: {alert.get('sector')} | "
                f"Reports: {alert.get('report_count')} | "
                f"Created: {alert.get('created_at')}"
            )

st.subheader("Recent reports")
try:
    reports_response = requests.get(
        f"{api_url}/reports",
        params={"limit": 20},
        timeout=5,
    )
    reports_response.raise_for_status()
    recent_reports = reports_response.json().get("reports", [])
except (requests.RequestException, ValueError):
    st.info("Start the backend to see recent reports.")
else:
    if not recent_reports:
        st.caption("No reports yet. Diagnose a symptom to create one.")
    else:
        st.dataframe(
            [
                {
                    "Time": report.get("created_at"),
                    "Pest": report.get("pest_id") or "unknown",
                    "Sector": report.get("sector") or "-",
                    "District": report.get("district") or "-",
                    "Reporter (hashed)": (report.get("reporter_hash") or "-")[:12],
                }
                for report in recent_reports
            ],
            use_container_width=True,
            hide_index=True,
        )
