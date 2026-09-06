
from pathlib import Path
import ast
import re
import shutil
import sys
from datetime import datetime

ROOT = Path(sys.argv[1]).resolve()
MAIN = ROOT / "webui" / "Main.py"
if not MAIN.exists():
    raise SystemExit(f"[ERROR] Missing {MAIN}")

backup = ROOT / ".ollama-studio-backups" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-v7-main") / "webui" / "Main.py"
backup.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(MAIN, backup)

text = MAIN.read_text(encoding="utf-8")

groups = """VIDEO_SOURCE_GROUPS = {
    "ollama_auto": ("ollama_auto_media",),
    "stock_video": ("pexels", "pixabay", "coverr"),
    "ai_video": (
        "metaso_minimax",
        "loomloom",
        "volcengine_seedance",
        "wavespeed",
        "ofox",
    ),
    "ai_image": ("openai_image",),
    "local": ("local",),
}"""
pat = re.compile(r"VIDEO_SOURCE_GROUPS\s*=\s*\{.*?\n\}", re.S)
if not pat.search(text):
    raise SystemExit("[ERROR] VIDEO_SOURCE_GROUPS block not found")
text = pat.sub(groups, text, count=1)

labels = """            video_source_labels = {
                "ollama_auto_media": "Ollama Director Auto Media",
                "pexels": tr("Pexels"),
                "pixabay": tr("Pixabay"),
                "coverr": tr("Coverr"),
                "wavespeed": tr("WaveSpeed AI Video"),
                "volcengine_seedance": tr("Volcano Engine Seedance"),
                "ofox": tr("OFox AI Video"),
                "metaso_minimax": tr("Metaso MiniMax H3"),
                "loomloom": tr("Shengsuan Cloud AI Video"),
                "openai_image": tr("OpenAI Compatible Text-to-Image"),
                "local": tr("Local file"),
            }"""
label_pat = re.compile(r'            video_source_labels\s*=\s*\{.*?\n            \}', re.S)
if not label_pat.search(text):
    raise SystemExit("[ERROR] video_source_labels block not found")
text = label_pat.sub(labels, text, count=1)

selector = """            saved_video_source_name = str(
                config.app.get("video_source", "ollama_auto_media")
                or "ollama_auto_media"
            )
            params.video_source = grouped_selectbox(
                tr("Video Source"),
                groups=(
                    ("Ollama Director", VIDEO_SOURCE_GROUPS["ollama_auto"]),
                    (tr("Stock Video"), VIDEO_SOURCE_GROUPS["stock_video"]),
                    (tr("AI Video"), VIDEO_SOURCE_GROUPS["ai_video"]),
                    (tr("AI Image"), VIDEO_SOURCE_GROUPS["ai_image"]),
                    (tr("Local Material"), VIDEO_SOURCE_GROUPS["local"]),
                ),
                default_value=saved_video_source_name,
                key="video_source_select",
                format_func=video_source_labels.get,
                settings_label=tr("Configure Material Sources"),
                on_settings=_open_material_settings_dialog,
            )
            _set_runtime_config("app", "video_source", params.video_source)"""
sel_pat = re.compile(
    r'            saved_video_source_name\s*=\s*str\(.*?'
    r'            _set_runtime_config\("app",\s*"video_source",\s*params\.video_source\)',
    re.S,
)
if not sel_pat.search(text):
    raise SystemExit("[ERROR] video source selector block not found")
text = sel_pat.sub(selector, text, count=1)

allow = """        if params.video_source not in [
            "ollama_auto_media",
            "pexels",
            "pixabay",
            "coverr",
            "wavespeed",
            "volcengine_seedance",
            "ofox",
            "metaso_minimax",
            "loomloom",
            "openai_image",
            "local",
        ]:
            _remove_active_generation_task(task_id)
            st.error(tr("Please Select a Valid Video Source"))
            st.stop()"""
allow_pat = re.compile(
    r'        if params\.video_source not in \[.*?'
    r'            st\.error\(tr\("Please Select a Valid Video Source"\)\)\n'
    r'            st\.stop\(\)',
    re.S,
)
if not allow_pat.search(text):
    raise SystemExit("[ERROR] Generate Video validation block not found")
text = allow_pat.sub(allow, text, count=1)

# Remove prior custom duration selector if our earlier patch already added it.
text = re.sub(
    r'\n\s*params\.target_duration_minutes\s*=\s*st\.(?:select_slider|slider)\(.*?\n\s*\)\n',
    '\n',
    text,
    flags=re.S,
)
anchor = '            _set_runtime_config("app", "video_source", params.video_source)\n'
duration = """            params.target_duration_minutes = st.select_slider(
                "Video duration target",
                options=[1, 3, 5, 8, 10],
                value=int(getattr(params, "target_duration_minutes", 3) or 3),
                key="ollama_duration_target_v7",
            )
            if params.video_source == "ollama_auto_media":
                st.caption(
                    "Ollama Director · qwen3:8b · Automatic media · "
                    "Wikimedia + Internet Archive + Pexels fallback · Script order preserved"
                )
"""
if anchor not in text:
    raise SystemExit("[ERROR] runtime config anchor not found")
text = text.replace(anchor, anchor + duration, 1)

tree = ast.parse(text, filename=str(MAIN))
groups_value = None
for node in tree.body:
    if isinstance(node, ast.Assign):
        if any(isinstance(t, ast.Name) and t.id == "VIDEO_SOURCE_GROUPS" for t in node.targets):
            groups_value = ast.literal_eval(node.value)
            break
if groups_value is None:
    raise SystemExit("[ERROR] Could not parse VIDEO_SOURCE_GROUPS")
flat = [x for values in groups_value.values() for x in values]
dupes = sorted({x for x in flat if flat.count(x) > 1})
if dupes:
    raise SystemExit(f"[ERROR] Duplicate source values: {dupes}")
for required in ["ollama_auto_media", "pexels", "pixabay", "coverr", "local"]:
    if required not in flat:
        raise SystemExit(f"[ERROR] Missing required source: {required}")

MAIN.write_text(text, encoding="utf-8")
print("[OK] Main.py syntax valid")
print("[OK] Video-source options unique")
print("[OK] Ollama Director + Pexels both available")
print(f"[OK] Backup: {backup}")
