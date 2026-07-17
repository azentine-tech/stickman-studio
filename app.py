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
st.caption("Bulk-generate stickman scene images from a timestamped transcript — 100% free, no API keys, powered by Pollinations.ai. Optionally guide the art style with up to 3 reference images.")

POLLINATIONS_IMAGE_BASE = "https://image.pollinations.ai/prompt/"
POLLINATIONS_TEXT_URL = "https://text.pollinations.ai/"
MIN_SECONDS_BETWEEN_IMAGE_CALLS = 16  # anonymous rate limit is ~1 req/15s
DEFAULT_REFERRER = "stickman-storyboard-studio"  # server-side calls send no browser Referer by default,
                                                  # and Pollinations' free tier increasingly wants one set

# ---------------- Session state ----------------
defaults = {
    "all_scenes": [],           # list of {"timestamp": str, "action": str}
    "generated_files": {},       # filename -> bytes
    "current_index": 0,
    "chat_messages": [],
    "raw_transcript_text": "",
    "style_ref_description": "",     # text description of uploaded reference images' style
    "style_ref_uploaded_names": [],  # names of files already analyzed, to avoid re-analyzing
    "pollinations_token": "",        # optional free token from auth.pollinations.ai
    "pollinations_referrer": "",     # optional referrer string
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


import base64
import mimetypes


def pollinations_auth():
    """
    Returns (extra_query_params, extra_headers). A referrer is always included
    since server-side requests send no browser Referer header, and Pollinations'
    free tier increasingly wants one for anonymous traffic. A free token from
    auth.pollinations.ai (optional, set in the sidebar) raises limits further.
    """
    token = st.session_state.get("pollinations_token", "").strip()
    referrer = st.session_state.get("pollinations_referrer", "").strip() or DEFAULT_REFERRER
    params = {"referrer": referrer}
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return params, headers


def call_pollinations_chat(messages, timeout=30, model="openai"):
    """
    Calls Pollinations' OpenAI-compatible chat endpoint (handles both plain text
    and vision messages). Tries the primary text.pollinations.ai/openai endpoint,
    then falls back to gen.pollinations.ai/openai if the first fails — some
    anonymous traffic gets routed differently between the two.
    Returns (content, error_message).
    """
    extra_params, extra_headers = pollinations_auth()
    headers = {"Content-Type": "application/json", **extra_headers}
    payload = {"model": model, "messages": messages}

    last_error = None
    for base in (f"{POLLINATIONS_TEXT_URL}openai", "https://gen.pollinations.ai/openai"):
        try:
            resp = requests.post(base, json=payload, params=extra_params, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                if content:
                    return content, None
                last_error = "Received an empty response."
            else:
                last_error = f"{base} → HTTP {resp.status_code}: {resp.text[:300]}"
        except Exception as e:
            last_error = f"{base} → request failed: {e}"
    return None, last_error


def describe_style_from_images(image_files):
    """
    Sends up to 3 uploaded images to Pollinations' vision model as base64
    (no external hosting needed) and asks it to describe the visual art style
    in words. That description gets folded into every generation prompt, which
    is far more reliable than image-to-image conditioning on the free tier.
    Note: this must use a vision-capable model (openai-large) — the default
    "openai" model silently ignores image content and just answers as if no
    image were attached.
    Returns (description, error_message).
    """
    content = [{
        "type": "text",
        "text": (
            "These images are style references for a minimalist stickman explainer-video "
            "illustration. Describe ONLY the visual style in 2-3 sentences: line weight, "
            "color palette, shading, composition, and mood. Do not describe the subject "
            "matter or people in the images, only the drawing/art style itself. Output just "
            "the description, no preamble."
        ),
    }]
    for f in image_files:
        mime = mimetypes.guess_type(f.name)[0] or "image/jpeg"
        b64 = base64.b64encode(f.getvalue()).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })
    return call_pollinations_chat([{"role": "user", "content": content}], timeout=40, model="openai-large")


# ---------------- Sidebar: style ----------------
with st.sidebar:
    st.header("🖼️ Style Reference Images (optional)")
    st.caption(
        "Upload up to 3 images and Pollinations' vision model will describe their art style "
        "in words — that description then gets woven into every stickman prompt. No image "
        "hosting needed, and nothing is saved permanently by this app."
    )
    style_ref_files = st.file_uploader(
        "Style reference images", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key="style_ref_uploader"
    )
    if style_ref_files and len(style_ref_files) > 3:
        st.warning("Only the first 3 images will be used.")
        style_ref_files = style_ref_files[:3]

    if style_ref_files:
        new_names = [f.name for f in style_ref_files]
        if new_names != st.session_state.style_ref_uploaded_names:
            with st.spinner("Analyzing style of uploaded images..."):
                description, err = describe_style_from_images(style_ref_files)
            if description:
                st.session_state.style_ref_description = description
            else:
                st.error(f"Couldn't analyze the images: {err}")
                st.session_state.style_ref_description = ""
            st.session_state.style_ref_uploaded_names = new_names

        cols = st.columns(len(style_ref_files))
        for idx, f in enumerate(style_ref_files):
            with cols[idx]:
                st.image(f, caption=f"Ref {idx+1}", use_container_width=True)

        if st.session_state.style_ref_description:
            st.session_state.style_ref_description = st.text_area(
                "Detected style (feel free to edit)", value=st.session_state.style_ref_description, height=90
            )
            use_style_refs = st.checkbox("Apply this style description to generation", value=True)
        else:
            use_style_refs = False
    else:
        st.session_state.style_ref_description = ""
        st.session_state.style_ref_uploaded_names = []
        use_style_refs = False

    st.write("---")
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
    st.header("🔑 Reliability (optional)")
    st.caption(
        "Anonymous free-tier calls can get rate-limited or rejected. A free token from "
        "[auth.pollinations.ai](https://auth.pollinations.ai) raises those limits — not required, but helps."
    )
    st.session_state.pollinations_token = st.text_input(
        "Free Pollinations token (optional)", value=st.session_state.pollinations_token, type="password"
    )
    st.session_state.pollinations_referrer = st.text_input(
        "Referrer / app name (optional)", value=st.session_state.pollinations_referrer,
        placeholder=DEFAULT_REFERRER,
    )

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
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": narration},
    ]
    for attempt in range(retries + 1):
        content, err = call_pollinations_chat(messages, timeout=20)
        if content:
            return content.strip('"')
        time.sleep(2)
    # Fallback: just truncate the narration itself
    return narration[:120]


def generate_image_bytes(prompt, width, height, seed=None, retries=2):
    encoded = urllib.parse.quote(prompt)
    url = f"{POLLINATIONS_IMAGE_BASE}{encoded}"
    extra_params, extra_headers = pollinations_auth()
    params = {"width": width, "height": height, "nologo": "true", **extra_params}
    if seed is not None:
        params["seed"] = seed
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers=extra_headers, timeout=30)
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

    granularity = st.radio(
        "Scene boundaries",
        ["Match each timestamp line exactly (recommended)", "Merge nearby lines into ~N-second scenes"],
        index=0,
        help="Exact mode makes one image per timestamp in your transcript — the safest way to keep images "
             "in sync with the actual video timing. Merge mode combines short lines into fewer, longer scenes.",
    )
    target_seconds = None
    if granularity.startswith("Merge"):
        target_seconds = st.slider("Target scene length (seconds)", 3, 30, 8)

    convert_clicked = st.button("🪄 Convert transcript → stickman scenes", type="primary")

    if convert_clicked:
        if not raw_text.strip():
            st.error("Paste a transcript first.")
        else:
            # Try VTT-style narration parsing first
            blocks = parse_timed_transcript(raw_text)
            scenes_out = []
            if blocks:
                if target_seconds is None:
                    # One scene per original transcript timestamp — no merging, no re-derived ranges.
                    scene_units = [
                        {"timestamp": f"{b['start']}-{b['end']}".replace(":", "_"), "narration": b["text"]}
                        for b in blocks
                        if b["text"].strip()
                    ]
                else:
                    scene_units = group_into_scenes(blocks, target_seconds=target_seconds)

                progress = st.progress(0)
                status = st.empty()
                for idx, sc in enumerate(scene_units):
                    status.text(f"Converting scene {idx+1}/{len(scene_units)} to a visual prompt ({sc['timestamp']})...")
                    visual = narration_to_visual_prompt(sc["narration"])
                    scenes_out.append({"timestamp": sc["timestamp"], "action": visual})
                    progress.progress((idx + 1) / len(scene_units))
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
                est_minutes = round(len(scenes_out) * MIN_SECONDS_BETWEEN_IMAGE_CALLS / 60, 1)
                st.success(
                    f"Created {len(scenes_out)} scenes. Head to tab 2 to generate images "
                    f"(roughly {est_minutes} min for all of them, due to the free-tier rate limit)."
                )
                if target_seconds is None and len(scenes_out) > 40:
                    st.info(
                        "Your transcript has a lot of very short timestamp lines, so this made a lot of scenes. "
                        "If that's more images than you want, switch to 'Merge nearby lines' above and re-convert."
                    )
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

        active_style_desc = st.session_state.style_ref_description if use_style_refs else ""
        if active_style_desc:
            st.caption("🖼️ Applying the detected style description from your uploaded reference images to every scene.")
        combined_style = f"{style_instruction}, {active_style_desc}" if active_style_desc else style_instruction

        BATCH_CHUNK = 10  # generated and shown 10 at a time, automatically, until everything is done

        if current_idx < total_scenes:
            remaining = total_scenes - current_idx
            if st.button(f"🚀 Generate all {remaining} remaining images (in batches of {BATCH_CHUNK})", type="primary"):
                overall_progress = st.progress(0)
                overall_status = st.empty()
                used_names = set(st.session_state.generated_files.keys())

                scenes_to_run = st.session_state.all_scenes[current_idx:]
                done_count = 0

                for chunk_start in range(0, len(scenes_to_run), BATCH_CHUNK):
                    chunk = scenes_to_run[chunk_start:chunk_start + BATCH_CHUNK]
                    st.write(f"#### Batch: scenes {current_idx + chunk_start + 1}–{current_idx + chunk_start + len(chunk)} of {total_scenes}")
                    img_cols = st.columns(min(5, len(chunk)))

                    for i, scene in enumerate(chunk):
                        label = scene["timestamp"]
                        action = scene["action"]
                        full_prompt = f"{action}, {combined_style}"
                        global_i = current_idx + chunk_start + i
                        seed_val = global_i if use_seed else None

                        overall_status.text(f"Generating {done_count + 1}/{remaining} — {label}")
                        img_bytes = generate_image_bytes(
                            full_prompt, img_width, img_height, seed=seed_val
                        )

                        if img_bytes:
                            # Name the file after its timestamp; de-duplicate if two scenes share one.
                            base_name = f"{label}.png"
                            fname = base_name
                            dup = 2
                            while fname in used_names:
                                fname = f"{label}_{dup}.png"
                                dup += 1
                            used_names.add(fname)
                            st.session_state.generated_files[fname] = img_bytes
                            with img_cols[i % len(img_cols)]:
                                st.image(img_bytes, caption=fname, use_container_width=True)
                        else:
                            st.error(f"❌ Pollinations timed out for scene {label} after retries — skipped. Re-run to retry just the gaps.")

                        done_count += 1
                        overall_progress.progress(done_count / remaining)
                        st.session_state.current_index = current_idx + chunk_start + i + 1

                        if done_count < remaining:
                            time.sleep(MIN_SECONDS_BETWEEN_IMAGE_CALLS)

                overall_status.text("Done.")
                st.success(f"Generated {done_count} images.")
                st.rerun()
        else:
            st.balloons()
            st.success("🎉 All scenes generated!")

    if st.session_state.generated_files:
        st.write("---")
        st.subheader("📥 Download all images")
        st.write(f"Images stored: **{len(st.session_state.generated_files)}**, each named after its timestamp, all in one flat ZIP folder.")

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
    st.caption("Free text chat via Pollinations — ask it to draft narration, suggest scene splits, or tweak stickman prompts. Attach up to 3 images for it to look at, too.")

    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            if msg.get("image_previews"):
                cols = st.columns(len(msg["image_previews"]))
                for c, img in zip(cols, msg["image_previews"]):
                    with c:
                        st.image(img, width=150)
            st.markdown(msg["content"])

    chat_attachments = st.file_uploader(
        "📎 Attach up to 3 images (optional)",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="chat_image_uploader",
    )
    if chat_attachments and len(chat_attachments) > 3:
        st.warning("Only the first 3 images will be sent.")
        chat_attachments = chat_attachments[:3]
    if chat_attachments:
        cols = st.columns(len(chat_attachments))
        for c, f in zip(cols, chat_attachments):
            with c:
                st.image(f, caption="Attached", width=150)

    if user_msg := st.chat_input("e.g. 'Split this into 8 stickman scenes about the hedonic treadmill'"):
        attached = [(f.name, f.getvalue()) for f in chat_attachments] if chat_attachments else []
        preview_imgs = [b for _, b in attached]

        st.session_state.chat_messages.append({
            "role": "user", "content": user_msg, "image_previews": preview_imgs
        })
        with st.chat_message("user"):
            if preview_imgs:
                cols = st.columns(len(preview_imgs))
                for c, img in zip(cols, preview_imgs):
                    with c:
                        st.image(img, width=150)
            st.markdown(user_msg)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            placeholder.markdown("🧠 *thinking...*")
            system_instruction = (
                "You are an expert short-video producer. Write concise, engaging scripts with "
                "clear timestamp brackets like [00:00 - 00:05], and suggest a matching minimalist "
                "stickman visual for each line. If images are attached, look at them closely and use "
                "them as context or style inspiration as relevant to the request."
            )
            messages_payload = [{"role": "system", "content": system_instruction}]

            # Replay recent history as plain text (attachments are only sent live, not replayed)
            for m in st.session_state.chat_messages[-6:-1]:
                messages_payload.append({"role": m["role"], "content": m["content"]})

            # Current turn: attach any images inline if present
            if attached:
                turn_content = [{"type": "text", "text": user_msg}]
                for fname, fbytes in attached:
                    mime = mimetypes.guess_type(fname)[0] or "image/jpeg"
                    b64 = base64.b64encode(fbytes).decode()
                    turn_content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
                messages_payload.append({"role": "user", "content": turn_content})
                # openai-large is the vision-capable model; the default "openai" model
                # silently ignores image content and answers as if nothing were attached
                model_to_use = "openai-large"
            else:
                messages_payload.append({"role": "user", "content": user_msg})
                model_to_use = "openai"

            reply, err = call_pollinations_chat(messages_payload, timeout=40, model=model_to_use)
            reply = reply or f"The free text service didn't respond ({err}). Try again in a moment."
            placeholder.markdown(reply)
            st.session_state.chat_messages.append({"role": "assistant", "content": reply, "image_previews": []})
