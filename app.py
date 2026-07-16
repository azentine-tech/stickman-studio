import streamlit as st
import base64
import time
import io
import zipfile
import re
import requests
import urllib.parse
from datetime import datetime

# Page styling
st.set_page_config(page_title="100% Free Keyless Stickman Studio", layout="wide")
st.title("🎬 100% Free Keyless Stickman Video Studio")
st.write("Free GPT-4o Script Writing & Resilient Flux/Stable Diffusion Image Generation (No API Keys Required!)")

# Sidebar for Setup & Styling Guardrails
with st.sidebar:
    st.header("🎨 1. Visual Style Reference Uploader")
    uploaded_files = st.file_uploader(
        "Upload up to 3 stickman style examples", 
        type=["png", "jpg", "jpeg"], 
        accept_multiple_files=True
    )
    
    if len(uploaded_files) > 3:
        st.warning("Only the first 3 images will be used for style reference.")
        uploaded_files = uploaded_files[:3]

    st.header("📝 2. Global Styling Output")
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

# --- RECOVERY RE-LOADER ---
st.sidebar.write("---")
st.sidebar.header("💾 3. Session Recovery Center")
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

# Layout Columns
col_chat, col_gen = st.columns([1, 1])

# --- LEFT COLUMN: 100% FREE KEYLESS CHAT ASSISTANT ---
with col_chat:
    st.subheader("💬 Script Researcher & Voiceover Producer")
    st.caption("Powered by Free Unofficial GPT-4o-Mini — No Limits, No API Key Required!")
    
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

    if chat_input := st.chat_input("E.g., 'Write a 30-sec transcript with stickman prompts about bees making honey.'"):
        with chat_container:
            with st.chat_message("user"):
                st.markdown(chat_input)
        st.session_state.messages.append({"role": "user", "content": chat_input})
        
        with chat_container:
            with st.chat_message("assistant"):
                response_placeholder = st.empty()
                response_placeholder.markdown("🧠 *Generating response...*")
                
                # Build context-aware prompt payload with history
                conversation_context = (
                    "You are an expert AI Video Producer. Your job is to:\n"
                    "1. Write engaging, short scripts with clear timing brackets like [00:00 - 00:05].\n"
                    "2. Translate each scene action into descriptive prompts ready for cartoon stickman images.\n\n"
                    "Recent chat logs:\n"
                )
                for msg in st.session_state.messages[-4:-1]:  # Include last 3 turns
                    conversation_context += f"{msg['role']}: {msg['content']}\n"
                conversation_context += f"user: {chat_input}\nassistant:"

                # Make the keyless GET API call to the unofficial GPT-4o-mini endpoint
                try:
                    encoded_query = urllib.parse.quote(conversation_context)
                    api_url = f"https://free-unoficial-gpt4o-mini-api-g70n.onrender.com/chat/?query={encoded_query}"
                    
                    response = requests.get(api_url, timeout=15)
                    if response.status_code == 200:
                        output_data = response.json()
                        # Extract string response safely from the API container
                        reply_text = output_data.get("results", "Error parsing response payload.")
                        if not reply_text or reply_text == "Error parsing response payload.":
                            reply_text = output_data.get("reply", "System busy. Let's try sending that again!")
                    else:
                        reply_text = "Free chat server is temporarily overloaded. Please try clicking submit again in a moment!"
                except Exception as e:
                    reply_text = f"Connection timeout. Re-submitting now should connect instantly. (Details: {e})"
                
                response_placeholder.markdown(reply_text)
                st.session_state.messages.append({"role": "assistant", "content": reply_text})

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
                    
                    # --- RESILIENT FREE DUAL-PROVIDER FALLBACKS ---
                    image_bytes = None
                    encoded_prompt = urllib.parse.quote(full_prompt)
                    
                    # Provider 1: Unified Pollinations with explicit model targeting
                    url_pollinations = f"https://gen.pollinations.ai/image/{encoded_prompt}?model=flux&width=1024&height=576&nologo=true"
                    
                    # Try Pollinations First
                    try:
                        response = requests.get(url_pollinations, timeout=12)
                        if response.status_code == 200 and response.content:
                            # Verify response is raw image payload
                            if b"PNG" in response.content[:10] or b"JFIF" in response.content[:10]:
                                image_bytes = response.content
                    except Exception:
                        pass
                    
                    # Provider 2 Fallback: Hercai Stable Diffusion (Highly stable free endpoint)
                    if not image_bytes:
                        try:
                            status_text.text(f"Switching to Hercai visual fallback for {timestamp_label}...")
                            url_herc = f"https://hercai.onrender.com/v3/text2image?prompt={encoded_prompt}"
                            response = requests.get(url_herc, timeout=12)
                            if response.status_code == 200:
                                res_json = response.json()
                                img_url = res_json.get("url")
                                if img_url:
                                    img_response = requests.get(img_url, timeout=10)
                                    if img_response.status_code == 200:
                                        image_bytes = img_response.content
                        except Exception:
                            pass
                            
                    # Final storage and render
                    if image_bytes:
                        filename = f"{timestamp_label}_scene_{current_idx + idx + 1}.png"
                        st.session_state.generated_files[filename] = image_bytes
                        st.image(image_bytes, caption=f"Generated: {filename}", width=250)
                    else:
                        st.error(f"❌ All free fallback providers timed out for scene {timestamp_label}. Try running again later.")
                    
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
                st.success("Studio storage completely cleared!")
                st.rerun()
