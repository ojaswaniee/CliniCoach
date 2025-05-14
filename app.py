import streamlit as st
import requests
import time
import os
from datetime import datetime

# ---------- CONFIGURATION ----------
st.set_page_config(page_title="CliniCoach", layout="centered")

# Make sure secrets are properly accessed
if "assemblyai" in st.secrets and "api_key" in st.secrets["assemblyai"]:
    ASSEMBLYAI_API_KEY = st.secrets["assemblyai"]["api_key"]
else:
    # Fallback to environment variables or provide a way to input keys
    ASSEMBLYAI_API_KEY = os.environ.get("ASSEMBLYAI_API_KEY", "")
    if not ASSEMBLYAI_API_KEY:
        ASSEMBLYAI_API_KEY = st.text_input("Enter your AssemblyAI API key:", type="password")
        if not ASSEMBLYAI_API_KEY:
            st.warning("Please provide an AssemblyAI API key to continue.")
            st.stop()

if "openrouter" in st.secrets and "api_key" in st.secrets["openrouter"]:
    OPENROUTER_API_KEY = st.secrets["openrouter"]["api_key"]
else:
    # Fallback to environment variables or provide a way to input keys
    OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
    if not OPENROUTER_API_KEY:
        OPENROUTER_API_KEY = st.text_input("Enter your OpenRouter API key:", type="password")
        if not OPENROUTER_API_KEY:
            st.warning("Please provide an OpenRouter API key to continue.")
            st.stop()

upload_endpoint = "https://api.assemblyai.com/v2/upload"
transcript_endpoint = "https://api.assemblyai.com/v2/transcript"

headers = {
    "authorization": ASSEMBLYAI_API_KEY,
    "content-type": "application/json"
}

openrouter_headers = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "http://localhost:8501",  # Update this to your actual domain in production
    "X-Title": "CliniCoach"
}

def get_gpt_response(prompt, model="openai/gpt-3.5-turbo"):
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}]
    }
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions", 
            json=data, 
            headers=openrouter_headers,
            timeout=30  # Add timeout to prevent hanging
        )
        response.raise_for_status()  # Raise an exception for 4XX/5XX responses
        result = response.json()
        
        if "choices" in result and len(result["choices"]) > 0:
            return result["choices"][0]["message"]["content"]
        else:
            return f"⚠️ GPT error: Unexpected response format {result}"
    except requests.exceptions.RequestException as e:
        return f"⚠️ GPT error: {str(e)}"
    except ValueError as e:  # JSON parsing error
        return f"⚠️ GPT error: Invalid response format - {str(e)}"
    except Exception as e:
        return f"⚠️ GPT error: {str(e)}"

# ---------- UI ----------
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

# Show API status
st.sidebar.markdown("### API Status")
api_status_container = st.sidebar.empty()

# Check API keys
api_status = {}
api_status["AssemblyAI"] = "✅ Connected" if ASSEMBLYAI_API_KEY else "❌ Missing API Key"
api_status["OpenRouter"] = "✅ Connected" if OPENROUTER_API_KEY else "❌ Missing API Key"

for api, status in api_status.items():
    api_status_container.markdown(f"**{api}**: {status}")

# ---------- Upload Section ----------
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

        # STEP 1: Upload to AssemblyAI
        def upload_to_assemblyai(file_path):
            with st.spinner("Uploading audio to AssemblyAI..."):
                try:
                    with open(file_path, "rb") as f:
                        response = requests.post(
                            upload_endpoint, 
                            headers={"authorization": ASSEMBLYAI_API_KEY}, 
                            files={"file": f},
                            timeout=60  # Add timeout to prevent hanging
                        )
                    
                    response.raise_for_status()
                    return response.json()["upload_url"]
                except Exception as e:
                    st.error(f"Failed to upload file to AssemblyAI: {str(e)}")
                    st.stop()

        audio_url = upload_to_assemblyai(file_path)
        st.info("Audio uploaded to AssemblyAI. Transcribing...")

        # STEP 2: Transcribe
        transcript_request = {
            "audio_url": audio_url,
            "language_code": "en_us"
        }

        try:
            response = requests.post(transcript_endpoint, json=transcript_request, headers=headers)
            response.raise_for_status()
            response_json = response.json()

            if "id" not in response_json:
                st.error("❌ Failed to submit transcription request.")
                st.json(response_json)
                st.stop()

            transcript_id = response_json["id"]
        except Exception as e:
            st.error(f"Transcription request failed: {str(e)}")
            st.stop()

        status = "queued"
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        with st.spinner("⏳ Processing transcript..."):
            retry_count = 0
            max_retries = 30  # Approximately 90 seconds of waiting
            
            while status not in ["completed", "error"] and retry_count < max_retries:
                try:
                    poll_response = requests.get(f"{transcript_endpoint}/{transcript_id}", headers=headers)
                    poll_response.raise_for_status()
                    poll_json = poll_response.json()
                    status = poll_json["status"]
                    
                    if status == "completed":
                        result = poll_json
                        progress_bar.progress(1.0)
                        status_text.success("Transcription completed!")
                        break
                    elif status == "error":
                        st.error("Transcription failed.")
                        st.json(poll_json)
                        st.stop()
                    else:
                        # Update progress based on status
                        progress_mapping = {
                            "queued": 0.1,
                            "processing": 0.5
                        }
                        progress = progress_mapping.get(status, 0.3)
                        progress_bar.progress(progress)
                        status_text.info(f"Transcription status: {status}")
                        
                except Exception as e:
                    st.warning(f"Error checking transcription status: {str(e)}. Retrying...")
                
                retry_count += 1
                time.sleep(3)
            
            if retry_count >= max_retries:
                st.error("Transcription timed out. Please try again later.")
                st.stop()

        transcript_text = result["text"]

        # STEP 3: View Transcript
        with st.expander("📄 View Transcript", expanded=True):
            st.write(transcript_text)
            
            # Option to download transcript
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            transcript_filename = f"transcript_{timestamp}.txt"
            st.download_button(
                label="Download Transcript",
                data=transcript_text,
                file_name=transcript_filename,
                mime="text/plain"
            )

        # STEP 4: Persona Inference
        st.markdown("## 🧬 Patient Profile Inference")
        with st.spinner("Analyzing patient profile..."):
            persona_prompt = f"""
            This is a transcript of a doctor-patient interaction:

            "{transcript_text}"

            Describe the patient's persona in one sentence. Include emotional tone, approximate age, and any inferred medical condition.
            Example: 'Anxious 50-year-old woman with diabetes, frustrated by long wait times.'
            """
            persona_summary = get_gpt_response(persona_prompt)
            
            if not persona_summary.startswith("⚠️ GPT error"):
                st.success("Patient profile analysis complete!")
                st.code(persona_summary, language="markdown")
            else:
                st.error("Failed to analyze patient profile")
                st.code(persona_summary)
                # Provide an option to retry
                if st.button("Retry Patient Profile Analysis"):
                    persona_summary = get_gpt_response(persona_prompt)
                    if not persona_summary.startswith("⚠️ GPT error"):
                        st.success("Patient profile analysis complete!")
                        st.code(persona_summary, language="markdown")
                    else:
                        st.error("Failed to analyze patient profile after retry")
                        st.code(persona_summary)

        # STEP 5: Coaching Feedback
        st.markdown("## 🧑‍⚕️ Communication Coaching Feedback")
        with st.spinner("Generating communication feedback..."):
            coaching_prompt = f"""
            You are a communication coach for doctors.

            Here is a transcript of how the doctor actually interacted with the patient:
            "{transcript_text}"

            The patient persona is:
            "{persona_summary}"
            
            Analyze the doctor's actual communication and provide 3 professional suggestions on how it could be improved.
            Focus on missed emotional cues, clarity, and tone.
            Format your response with clear headings and bullet points for easy reading.
            """
            coaching_feedback = get_gpt_response(coaching_prompt)
            
            if not coaching_feedback.startswith("⚠️ GPT error"):
                st.success("Communication coaching feedback generated!")
                st.markdown(coaching_feedback)
                
                # Option to download feedback
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                feedback_filename = f"coaching_feedback_{timestamp}.md"
                st.download_button(
                    label="Download Feedback",
                    data=coaching_feedback,
                    file_name=feedback_filename,
                    mime="text/markdown"
                )
            else:
                st.error("Failed to generate coaching feedback")
                st.code(coaching_feedback)
                # Provide an option to retry
                if st.button("Retry Coaching Feedback"):
                    coaching_feedback = get_gpt_response(coaching_prompt)
                    if not coaching_feedback.startswith("⚠️ GPT error"):
                        st.success("Communication coaching feedback generated!")
                        st.markdown(coaching_feedback)
                    else:
                        st.error("Failed to generate coaching feedback after retry")
                        st.code(coaching_feedback)

# Footer
st.markdown("---")
st.markdown("CliniCoach - Improving Healthcare Communication through AI")
st.caption("Powered by AssemblyAI and OpenRouter")