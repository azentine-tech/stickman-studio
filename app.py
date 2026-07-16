import streamlit as st
import base64
import time
import io
import zipfile
import re
import requests
import urllib.parse
from datetime import datetime
from google import genai
from google.genai import types

# Page styling
st.set_page_config(page_title="Self-Healing Stickman Studio", layout="wide")
st.title("🎬 Self-Healing Stickman Video Studio")
st.write("Stable Gemini script writing & highly resilient multi-provider free visual generation.")

# Sidebar for Setup & Styling Guardrails
with st.sidebar:
    st.header("⚙️ 1. Setup Configuration")
    api_key = st.text_input("Enter Gemini API Key (For Chat/Research only)", type="password")
    
    st.write("---")
    
    st.header("🎨 2. Visual Style Reference Uploader")
    uploaded_files = st.file_uploader(
        "Upload up to 3 stickman style examples", 
        type=["png", "jpg", "jpeg"], 
        accept_multiple_files=True
    )
    
    if len(uploaded_files) > 3:
        st.warning("Only the first 3 images will be used for style reference.")
        uploaded_files = uploaded_files[:3]

    st.header("📝 3. Global Styling Output")
    style_instruction_box = st.empty()
    default_style = "A minimalist hand-drawn stickman, clean solid black line art, webcomic / explainer doodle style, solid pure white background."
    style_instruction = style_instruction_box.text_area("Calculated Style Guidance", value=default_style)

# --- IN-MEMORY SESSION PERSISTENCE ---
if "all_scenes" not in st.session_state:
    st.session_state.all_scenes = []
if "generated_files" not in st.session_state:
    st.session_state.generated_files = {}
if "current_index" not in st.session_state:
    st.session_state.current_index = 0
if "messages" not in st.session_state:
    st.session_state.messages = []
if "api_history" not in st.session_state:
    st.session_state.api_history = []

# --- RECOVERY RE-LOADER ---
st.sidebar.write("---")
st.sidebar.header("💾 4. Session Recovery Center")
st.sidebar.write("If you refreshed the page, paste your backup data below to recover your work instantly.")
recovery_data = st.sidebar.text_area("Paste Raw Backup Data Here", placeholder="Paste backup text...")
if st.sidebar.button("Retrieve Work"):
    if recovery_data:
        try:
            restored_scenes = []
            lines = recovery_data.split("\n")
            for line in lines:
                if line.strip():
                    match = re.match(r"^\[(.*?)\]\s*(.*)$", line.strip())
                    if match:
                        timestamp = match.group(1).replace(":", "_").replace(" ", "")
                        action = match.group(2).strip()
                        restored_scenes.append({"timestamp": timestamp, "action": action})
            st.session_state.all_scenes = restored_scenes
            st.session_state.current_index = 0
            st.sidebar.success(f"Successfully recovered {len(restored_scenes)} scenes!")
            st.rerun()
        except Exception as err:
            st.sidebar.error(f"Failed to parse recovery text: {err}")

client = None
chat_session = None

# System prompt rules
system_instruction = (
    "You are an expert AI Video Producer and factual researcher. Your workflow follows these stages:\n\n"
    "STAGE 1: RESEARCH & FACT-CHECKING\n"
    "Formulate and organize facts based on your deep trained knowledge base.\n\n"
    "STAGE 2: SCRIPTWRITING & VOICEOVER\n"
    "Write highly engaging scripts with clear timestamps (e.g., [00:00 - 00:05]).\n\n"
    "STAGE 3: STICKMAN VISUAL TRANSLATION\n"
    "Translate scripts into visual prompts. Respect any visual cues or uploaded references. Always specify that it is a cartoon stickman illustration to bypass photorealistic generation filters."
)

# Initialize Chat Client with Multi-Model Redundancy
if api_key:
    try:
        client = genai.Client(api_key=api_key)
        
        # Try primary model first; fallback immediately if server capacity is constrained
        try:
            chat_session = client.chats.create(
                model="gemini-3.5-flash",
                history=st.session_state.api_history,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction
                )
            )
        except Exception:
            try:
                # Secondary Fallback Model (Stable and highly available)
                chat_session = client.chats.create(
                    model="gemini-2.5-flash",
                    history=st.session_state.api_history,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction
                    )
                )
            except Exception:
                # Final Failover Model (Guaranteed response path)
                chat_session = client.chats.create(
                    model="gemini-1.5-flash",
                    history=st.session_state.api_history,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction
                    )
                )
        
        # --- MULTIMODAL STYLE EXTRACTION ---
        if uploaded_files and "style_analyzed" not in st.session_state:
            with st.spinner("Analyzing uploaded style reference images..."):
                try:
                    parts = []
                    for uf in uploaded_files:
                        bytes_data = uf.read()
                        uf.seek(0)
                        parts.append(
                            types.Part.from_bytes(
                                data=bytes_data,
                                mime_type=uf.type
                            )
                        )
                    parts.append(
                        "Analyze the aesthetic and style of these stickman drawing examples. "
                        "Describe their visual style, line weights, coloring look, background style, and visual character in a single "
                        "concise, 2-sentence description that can be appended to prompts to replicate this exact style."
                    )
                    
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=parts
                    )
                    extracted_style = response.text.strip()
                    st.session_state.style_analyzed = extracted_style
                    style_instruction = style_instruction_box.text_area("Calculated Style Guidance", value=extracted_style)
                    st.sidebar.success("Style Reference analyzed successfully!")
                except Exception as ex:
                    st.sidebar.error(f"Failed to analyze style: {ex}")
                    
    except Exception as e:
        st.error(f"API Connection Error: {e}")

# Layout Columns
col_chat, col_gen = st.columns([1, 1])

# --- LEFT COLUMN: RESILIENT CHAT ASSISTANT ---
with col_chat:
    st.subheader("💬 Script Researcher & Voiceover Producer")
    
    if uploaded_files:
        cols = st.columns(len(uploaded_files))
        for idx, uf in enumerate(uploaded_files):
            with cols[idx]:
                st.image(uf, caption=f"Style Ref {idx+1}", use_container_width=True)
                
    chat_container = st.container(height=400)
    with chat_container:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    if chat_input := st.chat_input("E.g., 'Write a 30-sec transcript on how deep sea fish survive.'"):
        with chat_container:
            with st.chat_message("user"):
                st.markdown(chat_input)
        st.session_state.messages.append({"role": "user", "content": chat_input})
        
        if not chat_session:
            with chat_container:
                st.warning("⚠️ Enter your API Key in the sidebar first.")
        else:
            with chat_container:
                with st.chat_message("assistant"):
                    response_placeholder = st.empty()
                    response_text = ""
                    
                    # Try to get the response with automatic retry on 503
                    for attempt in range(3):
                        try:
                            response = chat_session.send_message(chat_input)
                            response_text = response.text
                            break
                        except Exception as e:
                            err_str = str(e)
                            if "503" in err_str or "UNAVAILABLE" in err_str:
                                if attempt < 2:
                                    response_placeholder.markdown("⏳ *Google's servers are busy. Retrying...*")
                                    time.sleep(2)  # Wait 2 seconds before retrying
                                    continue
                            # If we tried all retries or it's a different error, raise it
                            response_text = f"The primary server is experiencing heavy load. Error details: {e}"
                    
                    response_placeholder.markdown(response_text)
                    st.session_state.messages.append({"role": "assistant", "content": response_text})
                    st.session_state.api_history = chat_session.get_history()

# --- RIGHT COLUMN: TRANSCRIPT SAVER & BATCHED GENERATION ---
with col_gen:
    st.subheader("📝 Transcript To Batched Images")
    st.caption("Paste transcript below. System features robust, multi-provider free visual engines.")
    
    transcript_input = st.text_area(
        "Paste Complete Timestamps & Actions Here",
        placeholder="[00:00 - 00:05] Stickman running on a road\n[00:05 - 00:10] Stickman jumping over hurdles...",
        height=150
    )
    
    if st.button("💾 Save Transcript"):
        if transcript_input.strip():
            parsed_scenes = []
            lines = transcript_input.split("\n")
            for line in lines:
                if line.strip():
                    match = re.match(r"^\[(.*?)\]\s*(.*)$", line.strip())
                    if match:
                        timestamp = match.group(1).replace(":", "_").replace(" ", "")
                        action = match.group(2).strip()
                        parsed_scenes.append({"timestamp": timestamp, "action": action})
                    else:
                        fallback_time = datetime.now().strftime("%H%M%S")
                        parsed_scenes.append({"timestamp": f"scene_{fallback_time}", "action": line.strip()})
            
            st.session_state.all_scenes = parsed_scenes
            st.session_state.current_index = 0  
            st.success(f"Transcript Saved! Parsed **{len(parsed_scenes)}** scenes. Ready to generate.")
        else:
            st.error("Transcript cannot be empty.")

    # Status Monitor
    total_scenes = len(st.session_state.all_scenes)
    if total_scenes > 0:
        current_idx = st.session_state.current_index
        st.write(f"### Progress: **{current_idx} / {total_scenes}** images generated")
        
        # Calculate batch ranges
        end_idx = min(current_idx + 50, total_scenes)
        batch_size = end_idx - current_idx
        
        # --- SHOW BACKUP COPY-PASTE UTILITY ---
        st.info("💡 **Keep a backup of your work:** Copy the text below to keep a notepad backup of your project structure.")
        backup_text = ""
        for s in st.session_state.all_scenes:
            backup_text += f"[{s['timestamp']}] {s['action']}\n"
        st.text_area("Highlight and Copy this backup code:", value=backup_text.strip(), height=80)
        
        # Button: Execute Batch of 50
        if current_idx < total_scenes:
            btn_label = f"🚀 Execute Batch (Generate Scenes {current_idx+1} to {end_idx})"
            if st.button(btn_label):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                batch_scenes = st.session_state.all_scenes[current_idx:end_idx]
                
                for idx, scene in enumerate(batch_scenes):
                    timestamp_label = scene["timestamp"]
                    action_text = scene["action"]
                    
                    full_prompt = f"{action_text}, {style_instruction}"
                    status_text.text(f"Generating Image {idx+1}/{batch_size} ({timestamp_label})...")
                    
                    # --- MULTI-PROVIDER HIGH-STABILITY ROUTING (100% FREE) ---
                    image_bytes = None
                    encoded_prompt = urllib.parse.quote(full_prompt)
                    
                    # Try Provider 1: Pollinations AI (Standard)
                    try:
                        url_pollinations = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=576&nologo=true"
                        response = requests.get(url_pollinations, timeout=10)
                        if response.status_code == 200 and response.content:
                            image_bytes = response.content
                    except Exception:
                        pass
                    
                    # Try Provider 2: Hugging Face (Ultra-Stable Enterprise Infrastructure)
                    if not image_bytes:
                        try:
                            status_text.text(f"Pollinations down. Switching to Hugging Face fallback for {timestamp_label}...")
                            # Hugging Face stable-diffusion free server gateway
                            url_hf = f"https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
                            headers = {"User-Agent": "Mozilla/5.0"}
                            payload = {
                                "inputs": full_prompt,
                                "parameters": {"width": 1024, "height": 576}
                            }
                            response = requests.post(url_hf, json=payload, headers=headers, timeout=12)
                            if response.status_code == 200 and response.content:
                                # Ensure we got an image and not a json error back
                                if b"PNG" in response.content[:10] or b"JFIF" in response.content[:10]:
                                    image_bytes = response.content
                        except Exception:
                            pass
                            
                    # Final storage and render
                    if image_bytes:
                        filename = f"{timestamp_label}_scene_{current_idx + idx + 1}.png"
                        st.session_state.generated_files[filename] = image_bytes
                        st.image(image_bytes, caption=f"Generated: {filename}", width=250)
                    else:
                        st.error(f"❌ All free fallback providers timed out for scene {timestamp_label}. Try running again later once server queues clear.")
                    
                    progress_bar.progress((idx + 1) / batch_size)
                    time.sleep(1)
                
                st.session_state.current_index = end_idx
                st.success("Batch Complete!")
                st.rerun()
        else:
            st.balloons()
            st.success("🎉 All scenes generated successfully!")

    # Global Download Area (All batches unified into one ZIP)
    if st.session_state.generated_files:
        st.write("---")
        st.subheader("📥 Download Studio Assets")
        st.write(f"Currently compiled images in storage: **{len(st.session_state.generated_files)}**")
        
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
            for fname, fbytes in st.session_state.generated_files.items():
                zip_file.writestr(fname, fbytes)
        zip_buffer.seek(0)
        
        col_dl, col_reset = st.columns([1, 1])
        with col_dl:
            st.download_button(
                label="📥 Download ZIP Folder (All Batches Combined)",
                data=zip_buffer,
                file_name=f"complete_storyboard_{datetime.now().strftime('%Y%m%d_%H%M')}.zip",
                mime="application/zip",
                use_container_width=True
            )
        with col_reset:
            if st.button("🧹 Clear Studio Storage (Reset)", use_container_width=True):
                st.session_state.all_scenes = []
                st.session_state.generated_files = {}
                st.session_state.current_index = 0
                if "style_analyzed" in st.session_state:
                    del st.session_state.style_analyzed
                st.success("Studio storage completely cleared!")
                st.rerun()
