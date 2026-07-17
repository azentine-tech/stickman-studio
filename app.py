import streamlit as st
import time
import io
import zipfile
import re
import requests
import urllib.parse
from datetime import datetime

# ============================================================
# Production-Scale Stickman Studio
# Free, keyless AI generation powered entirely by Pollinations.ai
#   - Text:  https://text.pollinations.ai/
#   - Image: https://image.pollinations.ai/prompt/{prompt}
# No signup, no API key required for either endpoint.
# Anonymous usage is rate-limited (~1 request / 15s per IP), so
# this app paces requests to respect that instead of hammering
# the service and getting silently throttled.
# ============================================================

st.set_page_config(page_title="Stickman Storyboard Studio", layout="wide")
st.title("🎬 Stickman Storyboard Studio")
st.caption("Bulk-generate stickman scene images from a timestamped transcript — 100% free, no API keys, powered by Pollinations.ai")

POLLINATIONS_IMAGE_BASE = "https://image.pollinations.ai/prompt/"
POLLINATIONS_TEXT_URL = "https://text.pollinations.ai/"
MIN_SECONDS_BETWEEN_IMAGE_CALLS = 16  # anonymous rate limit is ~1 req/15s

# ---------------- Session state ----------------
defaults = {
    "all_scenes": [],           # list of {"timestamp": str, "action": str}
    "generated_files": {},       # filename -> bytes
    "current_index": 0,
    "chat_messages": [],
    "raw_transcript_text": "",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------- Sidebar: style ----------------
with st.sidebar:
    st.header("🎨 Visual Style")
    default_style = (
        "minimalist hand-drawn stickman, clean solid black line art, "
        "webcomic explainer-doodle style, solid pure white background, no text, no watermark"
    )
    style_instruction = st.text_area("Style guidance appended to every prompt", value=default_style, height=100)

    st.header("⚙️ Generation Settings")
    img_width = st.selectbox("Width", [512, 640, 768, 1024], index=1)
    img_height = st.selectbox("Height", [512, 640, 768, 1024], index=1)
    use_seed = st.checkbox("Use a fixed seed per scene (more consistent style)", value=True)
    st.caption(f"Pacing: ~1 image every {MIN_SECONDS_BETWEEN_IMAGE_CALLS}s to respect Pollinations' free anonymous rate limit.")

    st.write("---")
    st.header("💾 Session Recovery")
    st.caption("Paste a backup below to restore scenes after a refresh.")
    recovery_data = st.text_area("Backup data", placeholder="[timestamp] action ...", key="recovery_box")
    if st.button("Restore scenes from backup"):
        restored = []
        for line in recovery_data.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^\[(.*?)\]\s*(.*)$", line)
            if m:
                restored.append({"timestamp": m.group(1), "action": m.group(2).strip()})
        if restored:
            st.session_state.all_scenes = restored
            st.session_state.current_index = 0
            st.success(f"Restored {len(restored)} scenes.")
            st.rerun()
        else:
            st.error("Couldn't parse any scenes from that text.")


# ============================================================
# Helper functions
# ============================================================

def parse_timed_transcript(text):
    """
    Parses a VTT-style narration transcript:
        00:00 --> 00:01
        Some spoken line.
    Returns list of {"start": "00:00", "end": "00:01", "text": "..."}
    """
    blocks = []
    lines = [l.rstrip() for l in text.split("\n")]
    i = 0
    time_re = re.compile(r"^(\d{1,2}:\d{2}(?::\d{2})?)\s*-->\s*(\d{1,2}:\d{2}(?::\d{2})?)")
    while i < len(lines):
        m = time_re.match(lines[i].strip())
        if m:
            start, end = m.group(1), m.group(2)
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip() and not time_re.match(lines[i].strip()):
                text_lines.append(lines[i].strip())
                i += 1
            blocks.append({"start": start, "end": end, "text": " ".join(text_lines)})
        else:
            i += 1
    return blocks


def group_into_scenes(blocks, target_seconds=10):
    """
    Groups consecutive narration lines into scenes roughly target_seconds long,
    so we don't generate one image per single spoken line.
    """
    def to_secs(t):
        parts = [int(p) for p in t.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        h, m, s = parts
        return h * 3600 + m * 60 + s

    scenes = []
    current_text = []
    scene_start = None
    scene_end = None
    for b in blocks:
        if scene_start is None:
            scene_start = b["start"]
        scene_end = b["end"]
        current_text.append(b["text"])
        if to_secs(scene_end) - to_secs(scene_start) >= target_seconds:
            scenes.append({
                "timestamp": f"{scene_start}-{scene_end}".replace(":", "_"),
                "narration": " ".join(current_text),
            })
            current_text = []
            scene_start = None
    if current_text:
        scenes.append({
            "timestamp": f"{scene_start}-{scene_end}".replace(":", "_"),
            "narration": " ".join(current_text),
        })
    return scenes


def narration_to_visual_prompt(narration, retries=2):
    """
    Uses Pollinations' free text endpoint to turn a chunk of narration
    into a short, concrete visual stickman action description.
    """
    system_msg = (
        "You convert narration into a single short visual scene description for a "
        "minimalist stickman explainer video. Output ONLY the visual description "
        "(one sentence, under 20 words), no preamble, no quotes, no timestamps. "
        "Describe a concrete pose, action, or simple symbolic scene a stickman "
        "illustrator could draw to represent the idea."
    )
    payload = {
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": narration},
        ],
        "model": "openai",
        "jsonMode": False,
        "private": True,
        "stream": False,
    }
    for attempt in range(retries + 1):
        try:
            resp = requests.post(POLLINATIONS_TEXT_URL, json=payload, timeout=20)
            if resp.status_code == 200 and resp.text.strip():
                cleaned = resp.text.strip().strip('"')
                return cleaned
        except Exception:
            pass
        time.sleep(2)
    # Fallback: just truncate the narration itself
    return narration[:120]


def generate_image_bytes(prompt, width, height, seed=None, retries=2):
    encoded = urllib.parse.quote(prompt)
    url = f"{POLLINATIONS_IMAGE_BASE}{encoded}"
    params = {"width": width, "height": height, "nologo": "true"}
    if seed is not None:
        params["seed"] = seed
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200 and resp.content and len(resp.content) > 500:
                return resp.content
            if resp.status_code == 429:
                time.sleep(MIN_SECONDS_BETWEEN_IMAGE_CALLS)
                continue
        except Exception:
            pass
        time.sleep(3)
    return None


# ============================================================
# Layout
# ============================================================
tab_transcript, tab_scenes, tab_chat = st.tabs(
    ["📄 1. Import Transcript", "🖼️ 2. Generate Images", "💬 3. Script Assistant"]
)

# ---------------- TAB 1: Import & convert transcript ----------------
with tab_transcript:
    st.subheader("Paste your raw narration transcript")
    st.caption(
        "Accepts VTT-style timing (`00:00 --> 00:05` on its own line, narration below it), "
        "or pre-written scene actions like `[00:00 - 00:05] Stickman running`."
    )
    raw_text = st.text_area(
        "Transcript",
        value=st.session_state.raw_transcript_text,
        height=280,
        placeholder="00:00 --> 00:01\nNothing is wrong.\n\n00:02 --> 00:02\nYour job is fine.\n...",
    )
    st.session_state.raw_transcript_text = raw_text

    col_a, col_b = st.columns(2)
    with col_a:
        target_seconds = st.slider("Group narration into scenes of about how many seconds?", 5, 30, 10)
    with col_b:
        st.write("")
        st.write("")
        convert_clicked = st.button("🪄 Convert transcript → stickman scenes", type="primary")

    if convert_clicked:
        if not raw_text.strip():
            st.error("Paste a transcript first.")
        else:
            # Try VTT-style narration parsing first
            blocks = parse_timed_transcript(raw_text)
            scenes_out = []
            if blocks:
                grouped = group_into_scenes(blocks, target_seconds=target_seconds)
                progress = st.progress(0)
                status = st.empty()
                for idx, sc in enumerate(grouped):
                    status.text(f"Converting scene {idx+1}/{len(grouped)} to a visual prompt...")
                    visual = narration_to_visual_prompt(sc["narration"])
                    scenes_out.append({"timestamp": sc["timestamp"], "action": visual})
                    progress.progress((idx + 1) / len(grouped))
                status.text("Done.")
            else:
                # Fall back to already-written [timestamp] action lines
                for line in raw_text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    m = re.match(r"^\[(.*?)\]\s*(.*)$", line)
                    if m:
                        scenes_out.append({
                            "timestamp": m.group(1).replace(":", "_").replace(" ", ""),
                            "action": m.group(2).strip(),
                        })
            if scenes_out:
                st.session_state.all_scenes = scenes_out
                st.session_state.current_index = 0
                st.success(f"Created {len(scenes_out)} scenes. Head to tab 2 to generate images.")
            else:
                st.error("Couldn't parse any scenes from that text — check the format.")

    if st.session_state.all_scenes:
        st.write("### Parsed scenes")
        for i, s in enumerate(st.session_state.all_scenes):
            st.write(f"**{i+1}. [{s['timestamp']}]** {s['action']}")

# ---------------- TAB 2: Generate images ----------------
with tab_scenes:
    total_scenes = len(st.session_state.all_scenes)
    if total_scenes == 0:
        st.info("No scenes yet — import a transcript in Tab 1 first.")
    else:
        current_idx = st.session_state.current_index
        st.write(f"### Progress: **{current_idx} / {total_scenes}** images generated")

        backup_text = "\n".join(
            f"[{s['timestamp']}] {s['action']}" for s in st.session_state.all_scenes
        )
        with st.expander("💡 Backup your scene list (copy/paste text)"):
            st.text_area("Backup", value=backup_text, height=100)

        batch_size_choice = st.number_input(
            "Batch size (images per click)", min_value=1, max_value=50, value=10, step=1
        )
        end_idx = min(current_idx + batch_size_choice, total_scenes)

        if current_idx < total_scenes:
            if st.button(f"🚀 Generate scenes {current_idx + 1}–{end_idx} of {total_scenes}"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                batch = st.session_state.all_scenes[current_idx:end_idx]
                img_cols = st.columns(min(4, len(batch)))

                for i, scene in enumerate(batch):
                    label = scene["timestamp"]
                    action = scene["action"]
                    full_prompt = f"{action}, {style_instruction}"
                    seed_val = (current_idx + i) if use_seed else None

                    status_text.text(f"Generating {i+1}/{len(batch)}  —  {label}")
                    img_bytes = generate_image_bytes(full_prompt, img_width, img_height, seed=seed_val)

                    if img_bytes:
                        fname = f"{label}_scene_{current_idx + i + 1}.png"
                        st.session_state.generated_files[fname] = img_bytes
                        with img_cols[i % len(img_cols)]:
                            st.image(img_bytes, caption=fname, use_container_width=True)
                    else:
                        st.error(f"❌ Pollinations timed out for scene {label} after retries. It will be skipped — you can re-run this batch to retry just the failures.")

                    progress_bar.progress((i + 1) / len(batch))
                    # Respect free-tier anonymous rate limit between requests
                    if i < len(batch) - 1:
                        time.sleep(MIN_SECONDS_BETWEEN_IMAGE_CALLS)

                st.session_state.current_index = end_idx
                st.success("Batch complete!")
                st.rerun()
        else:
            st.balloons()
            st.success("🎉 All scenes generated!")

    if st.session_state.generated_files:
        st.write("---")
        st.subheader("📥 Download all images")
        st.write(f"Images stored: **{len(st.session_state.generated_files)}**")

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            for fname, fbytes in st.session_state.generated_files.items():
                zf.writestr(fname, fbytes)
        zip_buffer.seek(0)

        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "📥 Download ZIP",
                data=zip_buffer,
                file_name=f"stickman_storyboard_{datetime.now().strftime('%Y%m%d_%H%M')}.zip",
                mime="application/zip",
                use_container_width=True,
            )
        with c2:
            if st.button("🧹 Clear all generated images", use_container_width=True):
                st.session_state.generated_files = {}
                st.session_state.current_index = 0
                st.success("Cleared.")
                st.rerun()

# ---------------- TAB 3: Chat assistant ----------------
with tab_chat:
    st.subheader("Script & prompt assistant")
    st.caption("Free text chat via Pollinations — ask it to draft narration, suggest scene splits, or tweak stickman prompts.")

    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if user_msg := st.chat_input("e.g. 'Split this into 8 stickman scenes about the hedonic treadmill'"):
        st.session_state.chat_messages.append({"role": "user", "content": user_msg})
        with st.chat_message("user"):
            st.markdown(user_msg)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            placeholder.markdown("🧠 *thinking...*")
            system_instruction = (
                "You are an expert short-video producer. Write concise, engaging scripts with "
                "clear timestamp brackets like [00:00 - 00:05], and suggest a matching minimalist "
                "stickman visual for each line."
            )
            messages_payload = [{"role": "system", "content": system_instruction}]
            messages_payload += st.session_state.chat_messages[-6:]
            reply = None
            try:
                resp = requests.post(
                    POLLINATIONS_TEXT_URL,
                    json={"messages": messages_payload, "model": "openai", "jsonMode": False, "private": True, "stream": False},
                    timeout=20,
                )
                if resp.status_code == 200 and resp.text.strip():
                    reply = resp.text.strip()
            except Exception:
                pass
            reply = reply or "The free text service timed out — try again in a moment."
            placeholder.markdown(reply)
            st.session_state.chat_messages.append({"role": "assistant", "content": reply})
