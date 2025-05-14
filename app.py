import streamlit as st
import requests
import time
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# ---------- CONFIGURATION ----------
ASSEMBLYAI_API_KEY = "4899c76ebd744d7c82e6a204d33ba9bf"
OPENROUTER_API_KEY = "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"

upload_endpoint = "https://api.assemblyai.com/v2/upload"
transcript_endpoint = "https://api.assemblyai.com/v2/transcript"

headers = {
    "authorization": ASSEMBLYAI_API_KEY,
    "content-type": "application/json"
}

openrouter_headers = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "http://localhost:8501",
    "X-Title": "CliniCoach"
}

def get_gpt_response(prompt, model="openai/gpt-3.5-turbo"):
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}]
    }
    response = requests.post("https://openrouter.ai/api/v1/chat/completions", json=data, headers=openrouter_headers)
    result = response.json()
    if "choices" in result:
        return result["choices"][0]["message"]["content"]
    else:
        return f"⚠️ GPT error: {result.get('error', {}).get('message', 'Unknown error')}"

# ---------- FIREBASE INIT ----------
if not firebase_admin._apps:
    firebase_key = json.loads(st.secrets["FIREBASE_JSON"])
    cred = credentials.Certificate(firebase_key)
    firebase_admin.initialize_app(cred)

# ---------- STREAMLIT LAYOUT ----------
st.set_page_config(page_title="CliniCoach", layout="centered")

st.markdown("""
# 🩺 **CliniCoach**
### Voice-Based Communication Feedback for Healthcare Professionals

CliniCoach helps healthcare professionals improve their communication by analyzing real doctor-patient voice interactions. Simply upload a recorded consultation and receive feedback on how to enhance clarity, empathy, and tone.
""")

with st.expander("🌿 How CliniCoach Works", expanded=False):
    st.markdown("""
**1. Audio Upload**  
You upload a real conversation between a doctor and a patient.

**2. Transcription (AssemblyAI)**  
The voice recording is transcribed into readable text using AI-powered speech recognition.

**3. Patient Persona Inference**  
An LLM analyzes the transcript and generates a persona describing the patient's tone, mood, and condition.

**4. Coaching Feedback**  
Using the actual doctor response and patient persona, CliniCoach provides constructive feedback on how to improve empathy, tone, and communication clarity.
    """)

# ---------- UPLOAD SECTION ----------
st.markdown("## 📂 Upload a Doctor-Patient Audio File")
st.caption("Supported formats: MP3, WAV, M4A")

audio_file = st.file_uploader("Select a conversation to analyze:", type=["mp3", "wav", "m4a"], key="audio_upload")

if audio_file:
    os.makedirs("audio", exist_ok=True)
    file_path = os.path.join("audio", audio_file.name)

    with open(file_path, "wb") as f:
        f.write(audio_file.getbuffer())

    st.audio(file_path, format="audio/mp3")
    st.markdown("### ✅ Upload complete.")

    if st.button("▶️ Start Analysis"):

        # ---------- STEP 1: Upload to AssemblyAI ----------
        def upload_to_assemblyai(file_path):
            with open(file_path, "rb") as f:
                response = requests.post(upload_endpoint, headers={"authorization": ASSEMBLYAI_API_KEY}, files={"file": f})
            if response.status_code != 200:
                st.error("Failed to upload file to AssemblyAI.")
                st.stop()
            return response.json()["upload_url"]

        audio_url = upload_to_assemblyai(file_path)
        st.info("Audio uploaded to AssemblyAI. Transcribing...")

        # ---------- STEP 2: Transcribe ----------
        transcript_request = {
            "audio_url": audio_url,
            "language_code": "en_us"
        }

        response = requests.post(transcript_endpoint, json=transcript_request, headers=headers)
        response_json = response.json()

        if "id" not in response_json:
            st.error("❌ Failed to submit transcription request.")
            st.json(response_json)
            st.stop()

        transcript_id = response_json["id"]

        status = "queued"
        with st.spinner("⏳ Processing transcript..."):
            while status not in ["completed", "error"]:
                poll_response = requests.get(f"{transcript_endpoint}/{transcript_id}", headers=headers)
                status = poll_response.json()["status"]
                if status == "completed":
                    result = poll_response.json()
                    break
                elif status == "error":
                    st.error("Transcription failed.")
                    st.json(poll_response.json())
                    st.stop()
                time.sleep(3)

        transcript_text = result["text"]

        # ---------- STEP 3: Display Transcript ----------
        with st.expander("📄 View Transcript"):
            st.write(transcript_text)

        # ---------- STEP 4: Persona Inference ----------
        st.markdown("## 🧬 Patient Profile Inference")

        persona_prompt = f"""
        This is a transcript of a doctor-patient interaction:

        "{transcript_text}"

        Describe the patient’s persona in one sentence. Include emotional tone, approximate age, and any inferred medical condition.
        Example: 'Anxious 50-year-old woman with diabetes, frustrated by long wait times.'
        """
        persona_summary = get_gpt_response(persona_prompt)
        st.code(persona_summary, language="markdown")

        # ---------- STEP 5: Coaching Feedback (based on real interaction) ----------
        st.markdown("## 🧑‍⚕️ Communication Coaching Feedback")

        coaching_prompt = f"""
        You are a communication coach for doctors.

        Here is a transcript of how the doctor actually interacted with the patient:
        "{transcript_text}"

        The patient persona is:
        "{persona_summary}"

        Analyze the doctor's actual communication and provide 3 professional suggestions on how it could be improved.
        Focus on missed emotional cues, clarity, and tone.
        """
        coaching_feedback = get_gpt_response(coaching_prompt)
        st.markdown(coaching_feedback)

        # ---------- SAVE TO FIRESTORE ----------
        session_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "filename": audio_file.name,
            "transcript": transcript_text,
            "persona": persona_summary,
            "feedback": coaching_feedback
        }

        try:
            db.collection("coaching_sessions").add(session_data)
            st.success("📁 Session saved to Firestore.")
        except Exception as e:
            st.warning("⚠️ Failed to save session to Firestore.")
            st.write(e)
