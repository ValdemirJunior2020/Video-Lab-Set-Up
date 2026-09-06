from pathlib import Path
import ast
import shutil
import sys
from datetime import datetime

ROOT = Path(sys.argv[1]).resolve()
PAYLOAD = Path(__file__).resolve().parent / "payload"
BACK = ROOT / ".ollama-studio-backups" / datetime.now().strftime("%Y%m%d-%H%M%S-v8-expressive")
BACK.mkdir(parents=True, exist_ok=True)


def read(rel):
    p = ROOT / rel
    if not p.exists():
        raise SystemExit(f"[ERROR] Missing expected file: {rel}")
    return p.read_text(encoding="utf-8")


def write(rel, text):
    p = ROOT / rel
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    if old == text:
        print("[OK]", rel)
        return
    if p.exists():
        b = BACK / rel
        b.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, b)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    print("[PATCHED]", rel)


def rw(rel, fn):
    write(rel, fn(read(rel)))


def copy_payload(rel):
    src = PAYLOAD / rel
    if not src.exists():
        raise SystemExit(f"[ERROR] Missing payload: {rel}")
    write(rel, src.read_text(encoding="utf-8"))


copy_payload("chatterbox_service/Dockerfile")
copy_payload("chatterbox_service/chatterbox_service.py")
copy_payload("app/services/emotional_tts.py")


def patch_compose(s):
    if "container_name: moneyprinterturbo-chatterbox" in s:
        return s
    service = '''  chatterbox:\n    build:\n      context: .\n      dockerfile: chatterbox_service/Dockerfile\n    container_name: moneyprinterturbo-chatterbox\n    environment:\n      HF_HOME: /models/huggingface\n      TRANSFORMERS_CACHE: /models/huggingface\n    volumes:\n      - chatterbox-models:/models\n      - ./reference_audio:/reference_audio\n    ports:\n      - "127.0.0.1:4123:4123"\n    restart: unless-stopped\n\n'''
    if "services:\n" not in s:
        raise SystemExit("[ERROR] docker-compose services block missing")
    s = s.replace("services:\n", "services:\n" + service, 1)
    s = s.replace("  webui:\n", "  webui:\n    depends_on:\n      - chatterbox\n", 1)
    s = s.replace("  api:\n", "  api:\n    depends_on:\n      - chatterbox\n", 1)
    if "\nvolumes:\n" not in s:
        s += "\nvolumes:\n  chatterbox-models:\n"
    return s


rw("docker-compose.yml", patch_compose)


def patch_task(s):
    if "    emotional_tts,\n" not in s:
        if "    auto_media,\n    local_tts,\n" not in s:
            raise SystemExit("[ERROR] Expected V7 task import block not found")
        s = s.replace(
            "    auto_media,\n    local_tts,\n",
            "    auto_media,\n    emotional_tts,\n    local_tts,\n",
            1,
        )

    old = '''        logger.info("no custom audio file provided, using local-first Piper TTS.")\n        audio_file = path.join(utils.task_dir(task_id), "audio.mp3")\n        sub_maker = None\n        local_ok = local_tts.synthesize(video_script, audio_file)\n        if not local_ok:\n            logger.warning("Piper unavailable; falling back to Edge TTS")\n            sub_maker = voice.tts(text=video_script, voice_name=voice.parse_voice_name(params.voice_name), voice_rate=params.voice_rate, voice_file=audio_file)'''
    new = '''        logger.info("no custom audio file provided, using expressive Chatterbox first.")\n        audio_file = path.join(utils.task_dir(task_id), "audio.mp3")\n        sub_maker = None\n        expressive_ok = emotional_tts.synthesize(video_script, audio_file)\n        if not expressive_ok:\n            logger.warning("Chatterbox unavailable; falling back to local Piper")\n            local_ok = local_tts.synthesize(video_script, audio_file)\n            if not local_ok:\n                logger.warning("Piper unavailable; falling back to Edge TTS")\n                sub_maker = voice.tts(\n                    text=video_script,\n                    voice_name=voice.parse_voice_name(params.voice_name),\n                    voice_rate=params.voice_rate,\n                    voice_file=audio_file,\n                )'''
    if old not in s and "using expressive Chatterbox first" not in s:
        raise SystemExit("[ERROR] Expected V7 Piper audio block not found")
    s = s.replace(old, new, 1)
    s = s.replace(
        '_mark_task_failed(task_id, "audio", "Piper and Edge TTS both failed")',
        '_mark_task_failed(task_id, "audio", "Chatterbox, Piper, and Edge TTS all failed")',
    )
    return s


rw("app/services/task.py", patch_task)


def patch_cfg(s):
    if "expressive_tts_enabled" not in s:
        s += '''\n# Local expressive narration - Chatterbox V8\nexpressive_tts_enabled = true\nexpressive_tts_profile = "sermon"\nchatterbox_base_url = "http://chatterbox:4123"\n'''
    return s


rw("config.example.toml", patch_cfg)


def patch_main(s):
    old = '"Wikimedia + Internet Archive + Pexels fallback · Script order preserved"'
    new = '"Wikimedia + Internet Archive + Pexels fallback · Script order preserved · "\n                    "Chatterbox expressive narration -> Piper fallback"'
    if old in s:
        s = s.replace(old, new, 1)
    return s


rw("webui/Main.py", patch_main)

for rel in [
    "app/services/emotional_tts.py",
    "app/services/task.py",
    "webui/Main.py",
    "chatterbox_service/chatterbox_service.py",
]:
    ast.parse(read(rel), filename=rel)

print("[SUCCESS] V8 expressive Chatterbox integration applied")
print("[SUCCESS] Fallback chain: Chatterbox -> Piper -> Edge")
