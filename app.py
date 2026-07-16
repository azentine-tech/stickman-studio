import streamlit as st
import base64
import time
import io
import zipfile
import re
from datetime import datetime
from google import genai
from google.genai import types

# Page styling
st.set_page_config(page_title="Fact-Checked Stickman Studio", layout="wide")
st.title("🎬 Stickman Video Production Studio (with Live Web Search)")
st.write("Draft fact-checked scripts, translate transcripts to visual prompts, and batch generate stickman art in one workspace.")

# Sidebar for Setup & Styling Guardrails
with st.sidebar:
    st.header("⚙️ 1. Setup Configuration")
    api_key = st.text_input("Enter Gemini API Key", type="password")
    
    st.header("🎨 2. Visual Style Guardrails")
    style_instruction = st.text_area(
        "Default Image Style",
        value="A minimalist hand-drawn stickman, clean solid black line art, webcomic / explainer doodle style, solid pure white background, no gradients, no shading."
    )
    st.info("The system automatically forces all generated images to strictly adhere to this visual style.")

# --- STATEFUL CHAT MEMORY & TOOLS INITIALIZATION ---
if "messages" not in st.session_state:
    st.session_state.messages = []

if "api_history" not in st.session_state:
    st.session_state.api_history = []

client = None
chat_session = None

if api_key:
    try:
        client = genai.Client(api_key=api_key)
        
        # Guide the AI to research, fact-check, and maintain strict memory constraints
        system_instruction = (
            "You are an expert AI Video Producer and factual researcher. Your workflow MUST follow these stages:\n\n"
            "STAGE 1: RESEARCH & FACT-CHECKING\n"
            "Whenever the user asks for a script, voiceover, or factual explanation, you MUST use the Google Search tool "
            "to look up the latest accurate facts, figures, and historical events. Do not guess or hallucinate. "
            "State your sources or compiled facts briefly to the user before diving into the draft.\n\n"
            "STAGE 2: SCRIPTWRITING & VOICEOVER\n"
            "Once facts are secured, write highly engaging, structured scripts with clear timestamps (e.g., [00:00 - 00:05]).\n\n"
            "STAGE 3: STICKMAN VISUAL TRANSLATION\n"
            "Translate each script block into a visual prompt. Continuously remember and respect any design constraints "
            "the user provides (e.g., 'always wears a top hat', 'always has a red cape'). Keep asking clarifying questions "
            "if you need more guidance on their vision."
        )
        
        # We enable the Google Search Tool for live web grounding
        google_search_tool = types.Tool(
            google_search=types.GoogleSearch()
        )
        
        chat_session = client.chats.create(
            model="gemini-2.5-flash",
            history=st.session_state.api_history,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=[google_search_tool] # Enables the real-time search engine!
            )
        )
    except Exception as e:
        st.error(f"API Connection Error: {e}")

# Main Layout
col_chat, col_gen = st.columns([1, 1])

# --- LEFT COLUMN: RESEARCHING CHAT ASSISTANT ---
with col_chat:
    st.subheader("💬 Script Researcher & Producer")
    st.caption("Instruct the AI to research a topic first, verify facts, write voiceovers, or help build your storyboard.")
    
    # Message Container
    chat_container = st.container(height=450)
    with chat_container:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    # Chat input box
    if chat_input := st.chat_input("E.g., 'Research and write a 30-sec script on how GPS works. Get the factual science right!'"):
        with chat_container:
            with st.chat_message("user"):
                st.markdown(chat_input)
        st.session_state.messages.append({"role": "user", "content": chat_input})
        
        if not chat_session:
            with chat_container:
                st.warning("⚠️ Please provide your Gemini API Key in the sidebar.")
        else:
            with chat_container:
                with st.chat_message("assistant"):
                    response_placeholder = st.empty()
                    try:
                        response = chat_session.send_message(chat_input)
                        
                        # Extract and render search query suggestions or sources if they exist
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

# --- RIGHT COLUMN: TRANSCRIPT PARSER & IMAGE GENERATOR ---
with col_gen:
    st.subheader("📝 Transcript To Bulk Images")
    st.caption("Paste your timestamped transcript here. The app parses each row, structures a prompt, and generates images in bulk.")
    
    default_transcript = (
        "[00:00 - 00:05] Stickman scratching his head looking confused\n"
        "[00:05 - 00:10] Stickman suddenly gets a bright idea with a lightbulb above his head\n"
        "[00:10 - 00:15] Stickman running forward happily waving"
    )
    
    transcript_input = st.text_area(
        "Paste Timestamps & Actions Here",
        value=default_transcript,
        height=200
    )
    
    # Parsing timestamps and actions
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
                
    if parsed_scenes:
        st.success(f"Parsed **{len(parsed_scenes)}** distinct timed scene(s) for generation.")
        
    if st.button("🚀 Execute Bulk Generation", disabled=not client or not parsed_scenes):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
            for idx, scene in enumerate(parsed_scenes):
                timestamp_label = scene["timestamp"]
                action_text = scene["action"]
                
                full_prompt = f"{action_text}, {style_instruction}"
                status_text.text(f"Generating Scene {idx+1}/{len(parsed_scenes)} ({timestamp_label})...")
                
                try:
                    response = client.models.generate_content(
                        model="gemini-2.5-flash-image",
                        contents=full_prompt,
                        config=types.GenerateContentConfig(
                            response_modalities=["image", "text"],
                        ),
                    )
                    
                    image_bytes = None
                    for part in response.candidates[0].content.parts:
                        if part.inline_data:
                            image_bytes = base64.b64decode(part.inline_data.data)
                            break
                    
                    if image_bytes:
                        filename = f"{timestamp_label}_scene_{idx+1}.png"
                        zip_file.writestr(filename, image_bytes)
                        st.image(image_bytes, caption=f"Filenamed: {filename}", width=250)
                    else:
                        st.error(f"Failed image capture for timestamp: {timestamp_label}")
                        
                except Exception as e:
                    st.error(f"Error generating timestamp {timestamp_label}: {e}")
                
                progress_bar.progress((idx + 1) / len(parsed_scenes))
                
                if idx < len(parsed_scenes) - 1:
                    time.sleep(6)
                    
        zip_buffer.seek(0)
        status_text.text("Bulk Image Generation Complete!")
        
        st.download_button(
            label="📥 Download ZIP Package",
            data=zip_buffer,
            file_name=f"timed_storyboard_{datetime.now().strftime('%Y%m%d_%H%M')}.zip",
            mime="application/zip"
        )
