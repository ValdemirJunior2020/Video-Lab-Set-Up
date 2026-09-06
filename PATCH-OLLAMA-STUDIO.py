from pathlib import Path
import re, shutil, sys
from datetime import datetime

ROOT = Path(sys.argv[1]).resolve()
BACKUP = ROOT / '.ollama-studio-backups' / datetime.now().strftime('%Y%m%d-%H%M%S')
BACKUP.mkdir(parents=True, exist_ok=True)

def read(rel):
    p = ROOT / rel
    if not p.exists():
        raise SystemExit(f'[ERROR] Missing expected upstream file: {rel}')
    return p.read_text(encoding='utf-8')

def write(rel, text):
    p = ROOT / rel
    old = p.read_text(encoding='utf-8') if p.exists() else ''
    if old == text:
        print(f'[OK] {rel}')
        return
    if p.exists():
        b = BACKUP / rel
        b.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, b)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')
    print(f'[PATCHED] {rel}')

write('Dockerfile', '''FROM python:3.11-slim-bookworm
WORKDIR /MoneyPrinterTurbo
ENV PYTHONPATH=/MoneyPrinterTurbo PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir --retries 4 --timeout 120 -r requirements.txt
COPY . .
EXPOSE 8501 8080
CMD ["streamlit","run","./webui/Main.py","--server.address=0.0.0.0","--server.port=8501","--browser.serverAddress=127.0.0.1","--server.enableCORS=True","--browser.gatherUsageStats=False","--client.toolbarMode=minimal","--logger.hideWelcomeMessage=True","--server.showEmailPrompt=False"]
''')

write('docker-compose.yml', '''x-common-volumes: &common-volumes
  - ./:/MoneyPrinterTurbo
services:
  webui:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: moneyprinterturbo-webui
    ports:
      - "127.0.0.1:8501:8501"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      OLLAMA_HOST: http://host.docker.internal:11434
    command: ["streamlit","run","./webui/Main.py","--server.address=0.0.0.0","--server.port=8501","--browser.serverAddress=127.0.0.1","--server.enableCORS=True","--browser.gatherUsageStats=False","--client.toolbarMode=minimal","--logger.hideWelcomeMessage=True","--server.showEmailPrompt=False"]
    volumes: *common-volumes
    restart: unless-stopped
  api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: moneyprinterturbo-api
    ports:
      - "127.0.0.1:8080:8080"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      OLLAMA_HOST: http://host.docker.internal:11434
    command: ["python3","main.py"]
    volumes: *common-volumes
    restart: unless-stopped
''')

s = read('app/services/llm.py')
s = re.sub(r'MAX_SCRIPT_PARAGRAPH_NUMBER\s*=\s*\d+', 'MAX_SCRIPT_PARAGRAPH_NUMBER = 120', s, count=1)
s = re.sub(r'MAX_SCRIPT_PROMPT_LENGTH\s*=\s*\d+', 'MAX_SCRIPT_PROMPT_LENGTH = 50000', s, count=1)
s = re.sub(r'MAX_SCRIPT_SYSTEM_PROMPT_LENGTH\s*=\s*\d+', 'MAX_SCRIPT_SYSTEM_PROMPT_LENGTH = 50000', s, count=1)
write('app/services/llm.py', s)

s = read('app/models/schema.py')
s = re.sub(r'paragraph_number: int = Field\(default=1, ge=1, le=\d+\)', 'paragraph_number: int = Field(default=8, ge=1, le=120)', s)
s = s.replace('video_script: str = ""  # Script used to generate the video', 'video_script: str = Field(default="", max_length=200000)  # long-form script supported')
s = s.replace('video_source: Optional[str] = "pexels"', 'video_source: Optional[str] = "ollama_auto_media"')
if 'target_duration_minutes:' not in s:
    s = s.replace('video_clip_duration: int = Field(default=5, ge=1)', 'video_clip_duration: int = Field(default=5, ge=1)\n    target_duration_minutes: int = Field(default=3, ge=1, le=10)')
s = s.replace('video_script_prompt: str = Field(default="", max_length=2000)', 'video_script_prompt: str = Field(default="", max_length=50000)')
s = s.replace('custom_system_prompt: str = Field(default="", max_length=8000)', 'custom_system_prompt: str = Field(default="", max_length=50000)')
write('app/models/schema.py', s)

s = read('app/models/llm_provider.py')
s = re.sub(r'DEFAULT_LLM_PROVIDER_ID\s*=\s*"[^"]+"', 'DEFAULT_LLM_PROVIDER_ID = "ollama"', s, count=1)
write('app/models/llm_provider.py', s)

auto_media = r'''import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

import requests
from loguru import logger

from app.models.schema import MaterialInfo
from app.services import llm, video
from app.utils import utils

USER_AGENT = "MoneyPrinterTurbo-Ollama-Studio/3.0"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_META = "https://archive.org/metadata/{}"


def _json_array(text: str):
    text = re.sub(r"```(?:json)?|```", "", text or "").strip()
    start, end = text.find("["), text.rfind("]")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def plan_scenes(script: str, target_minutes: int = 3, clip_seconds: int = 5):
    desired = max(8, min(180, math.ceil(max(target_minutes * 60, 60) / max(clip_seconds, 3))))
    prompt = f"""Analyze the narration below and create exactly enough ordered visual scenes for a {target_minutes}-minute video, aiming for about {desired} scenes. Do not rewrite, shorten, summarize, or reorder the narration. Return ONLY a JSON array. Each object must contain: scene_number, narration, visual_search_query, alternative_search_query, estimated_duration. Search queries must be concrete English phrases suitable for Wikimedia Commons and Internet Archive. For Bible/history subjects, prefer public-domain paintings, maps, archaeological sites, Jerusalem, deserts, manuscripts, church art, ancient architecture, and historical illustrations. Preserve script order.\n\nSCRIPT:\n{script}"""
    try:
        data = _json_array(llm._generate_response(prompt))
        scenes = []
        for i, item in enumerate(data[:desired], 1):
            if not isinstance(item, dict):
                continue
            scenes.append({
                "scene_number": i,
                "narration": str(item.get("narration", "")),
                "visual_search_query": str(item.get("visual_search_query", "")).strip(),
                "alternative_search_query": str(item.get("alternative_search_query", "")).strip(),
                "estimated_duration": float(item.get("estimated_duration") or clip_seconds),
            })
        if scenes:
            return scenes
    except Exception as exc:
        logger.warning(f"Ollama scene planner fallback: {exc}")

    chunks = [x.strip() for x in re.split(r"(?<=[.!?])\s+", script) if x.strip()]
    return [
        {
            "scene_number": i + 1,
            "narration": chunk,
            "visual_search_query": chunk[:120],
            "alternative_search_query": "historical illustration " + chunk[:90],
            "estimated_duration": clip_seconds,
        }
        for i, chunk in enumerate(chunks[:desired])
    ]


def _commons_search(query: str, limit: int = 8):
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": query, "gsrnamespace": 6, "gsrlimit": limit,
        "prop": "imageinfo", "iiprop": "url|mime|extmetadata",
        "iiurlwidth": 1920, "origin": "*",
    }
    response = requests.get(COMMONS_API, params=params, headers={"User-Agent": USER_AGENT}, timeout=35)
    response.raise_for_status()
    pages = (response.json().get("query") or {}).get("pages") or {}
    results = []
    for page in pages.values():
        info = (page.get("imageinfo") or [None])[0]
        if not info or str(info.get("mime", "")).lower() not in {"image/jpeg", "image/png", "image/webp"}:
            continue
        metadata = info.get("extmetadata") or {}
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        results.append({
            "provider": "Wikimedia Commons",
            "url": url,
            "page": info.get("descriptionurl", ""),
            "license": (metadata.get("LicenseShortName") or {}).get("value", ""),
            "creator": re.sub(r"<[^>]+>", "", (metadata.get("Artist") or {}).get("value", "")),
            "title": page.get("title", ""),
        })
    return results


def _archive_search(query: str, limit: int = 5):
    params = {
        "q": f"({query}) AND (mediatype:image OR mediatype:movies)",
        "fl[]": ["identifier", "title", "mediatype"],
        "rows": limit,
        "output": "json",
    }
    response = requests.get(IA_SEARCH, params=params, headers={"User-Agent": USER_AGENT}, timeout=35)
    response.raise_for_status()
    results = []
    for doc in response.json().get("response", {}).get("docs", []):
        identifier = doc.get("identifier")
        if not identifier:
            continue
        try:
            metadata = requests.get(IA_META.format(identifier), headers={"User-Agent": USER_AGENT}, timeout=25).json()
        except Exception:
            continue
        for file_info in metadata.get("files", []):
            name = str(file_info.get("name", ""))
            low = name.lower()
            if low.endswith((".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov")) and not low.endswith(("_thumb.jpg", "__ia_thumb.jpg")):
                meta = metadata.get("metadata") or {}
                results.append({
                    "provider": "Internet Archive",
                    "url": f"https://archive.org/download/{quote(identifier)}/{quote(name)}",
                    "page": f"https://archive.org/details/{quote(identifier)}",
                    "license": str(meta.get("licenseurl", "")),
                    "creator": str(meta.get("creator", "")),
                    "title": str(doc.get("title", identifier)),
                })
                break
    return results


def _download(item: dict, cache_dir: Path):
    digest = hashlib.sha256(item["url"].encode()).hexdigest()
    suffix = Path(item["url"].split("?")[0]).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov"}:
        suffix = ".jpg"
    path = cache_dir / f"{digest}{suffix}"
    if path.exists() and path.stat().st_size > 2048:
        return path
    temp = path.with_suffix(path.suffix + ".part")
    with requests.get(item["url"], headers={"User-Agent": USER_AGENT}, timeout=90, stream=True) as response:
        response.raise_for_status()
        with temp.open("wb") as handle:
            for chunk in response.iter_content(262144):
                if chunk:
                    handle.write(chunk)
    if temp.stat().st_size < 2048:
        temp.unlink(missing_ok=True)
        raise ValueError("downloaded media was too small")
    temp.replace(path)
    return path


def _make_motion_clip(image_path: Path, duration: int, scene_number: int):
    output = image_path.with_name(f"scene-{scene_number:03d}-motion.mp4")
    # Alternate subtle zoom directions so consecutive stills do not feel identical.
    zoom = "min(zoom+0.0008,1.12)" if scene_number % 2 else "if(lte(zoom,1.0),1.12,max(1.0,zoom-0.0008))"
    frames = max(75, int(duration * 30))
    vf = (
        f"scale=2400:-2,zoompan=z='{zoom}':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080:fps=30,"
        "format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", str(image_path),
        "-vf", vf, "-t", str(max(3, duration)), "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(output),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return output


def download_for_script(task_id: str, script: str, target_minutes: int, clip_seconds: int):
    task_dir = Path(utils.task_dir(task_id))
    output_dir = task_dir / "ollama_auto_media"
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path("storage/cache/ollama_auto_media")
    cache_dir.mkdir(parents=True, exist_ok=True)

    scenes = plan_scenes(script, target_minutes, clip_seconds)
    (output_dir / "scene_plan.json").write_text(json.dumps(scenes, indent=2, ensure_ascii=False), encoding="utf-8")

    used_urls = set()
    records = []
    materials = []
    for scene in scenes:
        candidates = []
        for query in (scene["visual_search_query"], scene["alternative_search_query"]):
            if not query:
                continue
            try:
                candidates.extend(_commons_search(query, 8))
            except Exception as exc:
                logger.warning(f"Wikimedia Commons search failed for {query!r}: {exc}")
            if not candidates:
                try:
                    candidates.extend(_archive_search(query, 5))
                except Exception as exc:
                    logger.warning(f"Internet Archive search failed for {query!r}: {exc}")

        chosen = None
        for item in candidates:
            if item["url"] in used_urls:
                continue
            try:
                source_path = _download(item, cache_dir)
                used_urls.add(item["url"])
                chosen = (item, source_path)
                break
            except Exception as exc:
                logger.warning(f"Automatic media download failed: {exc}")

        if not chosen:
            logger.warning(f"No usable media found for scene {scene['scene_number']}")
            continue

        item, source_path = chosen
        destination = output_dir / f"scene-{scene['scene_number']:03d}{source_path.suffix.lower()}"
        shutil.copy2(source_path, destination)
        scene_duration = max(3, int(scene.get("estimated_duration") or clip_seconds))
        material_path = destination
        if destination.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            try:
                material_path = _make_motion_clip(destination, scene_duration, scene["scene_number"])
            except Exception as exc:
                logger.warning(f"Ken Burns motion generation failed; using normal image preprocessing: {exc}")
        materials.append(MaterialInfo(
            provider="ollama_auto_media",
            url=str(material_path),
            duration=scene_duration,
            source_info={
                "search_term": scene["visual_search_query"],
                "source_page": item["page"],
                "creator": item["creator"],
            },
        ))
        records.append({
            **scene,
            "local_file": destination.name,
            "provider": item["provider"],
            "source_url": item["page"],
            "license": item["license"],
            "creator": item["creator"],
            "title": item["title"],
        })

    (output_dir / "attribution.json").write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / "ATTRIBUTION.md").write_text(
        "\n".join(
            f"- Scene {r['scene_number']}: {r['title']} — {r['provider']} — {r['license']} — {r['source_url']}"
            for r in records
        ),
        encoding="utf-8",
    )
    if not materials:
        return [], scenes
    processed = video.preprocess_video(materials=materials, clip_duration=clip_seconds)
    return [item.url for item in processed], scenes
'''
write('app/services/auto_media.py', auto_media)

s = read('app/services/task.py')
if '    auto_media,\n' not in s:
    s = s.replace('    elevenlabs_music,\n', '    auto_media,\n    elevenlabs_music,\n', 1)
s = s.replace('amount=8 if params.match_materials_to_script else 5,', 'amount=max(12, int(getattr(params, "target_duration_minutes", 3)) * 6) if params.match_materials_to_script else 8,')
needle = '''        video_script = llm.generate_script(\n            video_subject=params.video_subject,\n            language=params.video_language,\n            paragraph_number=params.paragraph_number,\n            video_script_prompt=params.video_script_prompt,\n            custom_system_prompt=params.custom_system_prompt,\n        )'''
replacement = '''        target_minutes = int(getattr(params, "target_duration_minutes", 3) or 3)\n        target_words = target_minutes * 145\n        duration_prompt = (params.video_script_prompt or "") + f"\\nCreate detailed long-form narration targeting about {target_minutes} minutes / {target_words} spoken words. Do not summarize. Develop the subject fully and naturally."\n        video_script = llm.generate_script(\n            video_subject=params.video_subject,\n            language=params.video_language,\n            paragraph_number=max(params.paragraph_number, target_minutes * 4),\n            video_script_prompt=duration_prompt,\n            custom_system_prompt=params.custom_system_prompt,\n        )'''
if needle in s:
    s = s.replace(needle, replacement, 1)
if 'video_script: str = "",' not in s:
    s = s.replace(
        '    loomloom_video_request: loomloom.LoomLoomConfirmedVideoRequest | None = None,\n):',
        '    loomloom_video_request: loomloom.LoomLoomConfirmedVideoRequest | None = None,\n    video_script: str = "",\n):',
        1,
    )
branch = '''    if params.video_source == "ollama_auto_media":\n        logger.info("\\n\\n## Searching media - Ollama Auto Media")\n        try:\n            files, scenes = auto_media.download_for_script(\n                task_id, video_script, int(getattr(params, "target_duration_minutes", 3)), params.video_clip_duration\n            )\n            sm.state.update_task(task_id, planned_scenes=len(scenes))\n        except Exception as exc:\n            _mark_task_failed(task_id, "searching_media", str(exc))\n            return None\n        if not files:\n            _mark_task_failed(task_id, "searching_media", "No usable automatic media was found from Wikimedia Commons or Internet Archive")\n            return None\n        return files\n\n'''
if 'params.video_source == "ollama_auto_media"' not in s:
    s = s.replace('    if params.video_source == "local":', branch + '    if params.video_source == "local":', 1)
call = '''        audio_duration,\n        loomloom_video_request=loomloom_video_request,\n    )'''
if call in s:
    s = s.replace(call, '''        audio_duration,\n        loomloom_video_request=loomloom_video_request,\n        video_script=video_script,\n    )''', 1)
write('app/services/task.py', s)

s = read('webui/Main.py')
if '"free_auto": ("ollama_auto_media",),' not in s:
    s = s.replace('VIDEO_SOURCE_GROUPS = {', 'VIDEO_SOURCE_GROUPS = {\n    "free_auto": ("ollama_auto_media",),', 1)
if '"ollama_auto_media": "Ollama Auto Media"' not in s:
    s = s.replace('                "pexels": tr("Pexels"),', '                "ollama_auto_media": "Ollama Auto Media",\n                "pexels": tr("Pexels"),', 1)
if '("Ollama Auto Media", VIDEO_SOURCE_GROUPS["free_auto"]),' not in s:
    s = s.replace('                groups=(\n', '                groups=(\n                    ("Ollama Auto Media", VIDEO_SOURCE_GROUPS["free_auto"]),\n', 1)
anchor = '            _set_runtime_config("app", "video_source", params.video_source)\n'
if 'ollama_duration_target' not in s and anchor in s:
    s = s.replace(anchor, anchor + '''\n            params.target_duration_minutes = st.select_slider(\n                "Video duration target", options=[1, 3, 5, 8, 10],\n                value=int(getattr(params, "target_duration_minutes", 3)),\n                key="ollama_duration_target",\n            )\n            if params.video_source == "ollama_auto_media":\n                st.caption("Ollama Studio · qwen3:8b · Automatic media · Wikimedia Commons + Internet Archive · Script order preserved")\n''', 1)
write('webui/Main.py', s)

s = read('config.example.toml')
s = re.sub(r'(?m)^llm_provider\s*=.*$', 'llm_provider = "ollama"', s, count=1)
s = re.sub(r'(?m)^ollama_model_name\s*=.*$', 'ollama_model_name = "qwen3:8b"', s, count=1)
s = re.sub(r'(?m)^ollama_base_url\s*=.*$', 'ollama_base_url = "http://host.docker.internal:11434/v1"', s, count=1)
s = re.sub(r'(?m)^video_source\s*=.*$', 'video_source = "ollama_auto_media"', s, count=1)
s = re.sub(r'(?m)^match_materials_to_script\s*=.*$', 'match_materials_to_script = true', s, count=1)
write('config.example.toml', s)

print(f'[SUCCESS] Ollama Studio patch applied. Backups: {BACKUP}')
