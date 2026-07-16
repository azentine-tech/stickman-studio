import streamlit as st
import base64
import time
import io
import zipfile
import re
from datetime import datetime
from google import genai
from google.genai import types
from PIL import Image

# Page styling
st.set_page_config(page_title="Production Scale Stickman Studio", layout="wide")
st.title("🎬 Production Scale Stickman Studio (Gemini 3.5 & Gemini 3.1 Image)")
st.write("Upload style examples, paste full transcripts, and generate styled assets in safe batches of 50.")

# Sidebar for Setup & Styling Guardrails
with st.sidebar:
    st.header("⚙️ 1. Setup Configuration")
    api_key = st.text_input("Enter Gemini API Key", type="password")
    
    st.header("🎨 2. Visual Style Reference Uploader")
    uploaded_files = st.file_uploader(
        "Upload up to 3 stickman style examples", 
        type=["png", "jpg", "jpeg"], 
        accept_multiple_files=True
    )
    
    # Restrict to maximum 3 files
    if len(uploaded_files) > 3:
        st.warning("Only the first 3 images will be used for style reference.")
        uploaded_files = uploaded_files[:3]

    st.header("📝 3. Global Styling Output")
    style_instruction_box = st.empty()
    default_style = "A minimalist hand-drawn stickman, clean solid black line art, webcomic / explainer doodle style, solid pure white background."
    style_instruction = style_instruction_box.text_area("Calculated Style Guidance", value=default_style)

# --- IN-MEMORY SESSION PERSISTENCE ---
# All scenes parsed from transcript
if "all_scenes" not in st.session_state:
    st.session_state.all_scenes = []
# Global storage for generated images: { filename: bytes }
if "generated_files" not in st.session_state:
    st.session_state.generated_files = {}
# Current progress pointer
if "current_index" not in st.session_state:
    st.session_state.current_index = 0
# Chat message logs
if "messages" not in st.session_state:
    st.session_state.messages = []
if "api_history" not in st.session_state:
    st.session_state.api_history = []

client = None
chat_session = None

# Initialize Client
if api_key:
    try:
        client = genai.Client(api_key=api_key)
        
        # Guide the AI chat
        system_instruction = (
            "You are an expert AI Video Producer and factual researcher. Your workflow follows these stages:\n\n"
            "STAGE 1: RESEARCH & FACT-CHECKING\n"
            "Whenever asked for a script/voiceover, use Google Search to verify facts before writing.\n\n"
            "STAGE 2: SCRIPTWRITING & VOICEOVER\n"
            "Write highly engaging scripts with clear timestamps (e.g., [00:00 - 00:05]).\n\n"
            "STAGE 3: STICKMAN VISUAL TRANSLATION\n"
            "Translate scripts into visual prompts. Respect any visual cues or uploaded references. Always specify that it is a cartoon stickman illustration to bypass photorealistic generation filters."
        )
        
        google_search_tool = types.Tool(
            google_search=types.GoogleSearch()
        )
        
        chat_session = client.chats.create(
            model="gemini-3.5-flash",
            history=st.session_state.api_history,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=[google_search_tool]
            )
        )
        
        # --- MULTIMODAL STYLE EXTRACTION ---
        if uploaded_files and "style_analyzed" not in st.session_state:
            with st.spinner("Analyzing uploaded style reference images..."):
                try:
                    parts = []
                    for uf in uploaded_files:
                        bytes_data = uf.read()
                        # Reset seek pointer so user can preview them
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
                        model="gemini-3.5-flash",
                        contents=parts
                    )
                    extracted_style = response.text.strip()
                    st.session_state.style_analyzed = extracted_style
                    # Update style prompt textarea on the screen
                    style_instruction = style_instruction_box.text_area("Calculated Style Guidance", value=extracted_style)
                    st.sidebar.success("Style Reference analyzed successfully!")
                except Exception as ex:
                    st.sidebar.error(f"Failed to analyze style: {ex}")
                    
    except Exception as e:
        st.error(f"API Connection Error: {e}")

# Layout Columns
col_chat, col_gen = st.columns([1, 1])

# --- LEFT COLUMN: RESEARCHING CHAT ASSISTANT ---
with col_chat:
    st.subheader("💬 Script Researcher & Voiceover Producer")
    
    # Preview uploaded reference files
    if uploaded_files:
        cols = st.columns(len(uploaded_files))
        for idx, uf in enumerate(uploaded_files):
            with cols[idx]:
                st.image(uf, caption=f"Style Ref {idx+1}", use_container_width=True)
                
    # Message Container
    chat_container = st.container(height=400)
    with chat_container:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    # Chat input box
    if chat_input := st.chat_input("E.g., 'Research how bees make honey and write a transcript.'"):
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
                    try:
                        response = chat_session.send_message(chat_input)
                        
                        response_text = response.text
                        if response.candidates and response.candidates[0].grounding_metadata:
                            metadata = response.candidates[0].grounding_metadata
                            if metadata.web_search_queries:
                                queries_str = ", ".join([f"'{q}'" for q in metadata.web_search_queries])
                                response_text += f"\n\n*(🔍 Facts verified using Google Search queries: {queries_str})*"
                        
                        response_placeholder.markdown(response_text)
                        st.session_state.messages.append({"role": "assistant", "content": response_text})
                        st.session_state.api_history = chat_session.get_history()
                    except Exception as e:
                        response_placeholder.markdown(f"Error: {e}")

# --- RIGHT COLUMN: TRANSCRIPT SAVER & BATCHED GENERATION ---
with col_gen:
    st.subheader("📝 Transcript To Batched Images")
    st.caption("Paste your entire video transcript once below. The AI will store it and let you process generations in batches of 50.")
    
    transcript_input = st.text_area(
        "Paste Complete Timestamps & Actions Here",
        placeholder="[00:00 - 00:05] Stickman running on a road\n[00:05 - 00:10] Stickman jumping over hurdles...",
        height=150
    )
    
    # Button to Parse & Lock in Transcript
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
            st.session_state.current_index = 0  # Reset pointer to the start
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
        
        # Button: Execute Batch of 50
        if current_idx < total_scenes:
            btn_label = f"🚀 Execute Batch (Generate Scenes {current_idx+1} to {end_idx})"
            if st.button(btn_label, disabled=not client):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                # Fetch only current batch scenes
                batch_scenes = st.session_state.all_scenes[current_idx:end_idx]
                
                for idx, scene in enumerate(batch_scenes):
                    timestamp_label = scene["timestamp"]
                    action_text = scene["action"]
                    
                    full_prompt = f"{action_text}, {style_instruction}"
                    status_text.text(f"Generating Image {idx+1}/{batch_size} ({timestamp_label})...")
                    
                    try:
                        # UPDATED: Changed model and request format to target gemini-3.1-flash-image
                        response = client.models.generate_content(
                            model="gemini-3.1-flash-image",
                            contents=full_prompt,
                            config=types.GenerateContentConfig(
                                response_modalities=["IMAGE", "TEXT"],
                                image_config=types.ImageConfig(
                                    aspect_ratio="16:9"
                                )
                            ),
                        )
                        
                        image_bytes = None
                        for part in response.candidates[0].content.parts:
                            if part.inline_data:
                                raw_data = part.inline_data.data
                                # Robust handling for both byte streams and encoded strings
                                if isinstance(raw_data, bytes):
                                    image_bytes = raw_data
                                else:
                                    try:
                                        image_bytes = base64.b64decode(raw_data)
                                    except Exception:
                                        image_bytes = raw_data
                                break
                        
                        if image_bytes:
                            filename = f"{timestamp_label}_scene_{current_idx + idx + 1}.png"
                            
                            # Save globally to the session state
                            st.session_state.generated_files[filename] = image_bytes
                            
                            # Render image locally on screen
                            st.image(image_bytes, caption=f"Generated: {filename}", width=250)
                        else:
                            st.error(f"Empty payload on scene {timestamp_label}")
                            
                    except Exception as e:
                        st.error(f"Error on Scene {current_idx + idx + 1}: {e}")
                    
                    progress_bar.progress((idx + 1) / batch_size)
                    
                    # Pause for 6 seconds to stay safely under API rate limits
                    if idx < batch_size - 1:
                        time.sleep(6)
                
                # Advance the pointer
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
        
        # Build ZIP File in RAM
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
