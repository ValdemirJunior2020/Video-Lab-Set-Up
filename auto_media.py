import hashlib
import html
import json
import math
import re
import shutil
import subprocess
import threading
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from loguru import logger

from app.config import config
from app.models.schema import MaterialInfo
from app.services import llm, scene_planner_agent, video
from app.utils import utils

USER_AGENT = "MoneyPrinterTurbo-Ollama-Director/6.0 (+local-media-retrieval)"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_META = "https://archive.org/metadata/{}"
PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"

_SESSION = requests.Session()
_retry = Retry(
    total=4,
    connect=3,
    read=3,
    status=4,
    backoff_factor=1.8,
    status_forcelist=(429, 500, 502, 503, 504),
    respect_retry_after_header=True,
    allowed_methods=frozenset(["GET"]),
)
_SESSION.mount("https://", HTTPAdapter(max_retries=_retry, pool_connections=8, pool_maxsize=8))
_SESSION.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})

_RATE_LOCK = threading.Lock()
_LAST_COMMONS = 0.0
_COMMONS_COOLDOWN_UNTIL = 0.0
_COMMONS_429S = 0
COMMONS_MIN_INTERVAL = 1.35
COMMONS_COOLDOWN_SECONDS = 90

STOPWORDS = {
    "the","and","for","with","from","into","over","under","this","that","their","they",
    "his","her","public","domain","historical","illustration","painting","image","photo",
    "video","biblical","bible","ancient","scene","journey","family","season","map","art","story"
}

BANNED_TITLE_TERMS = {
    "hitler","nazi","world war","civil war","american conflict","great rebellion","football",
    "baseball","celebrity","porn","adult","casino","gaming","trailer","movie rip","full documentary"
}


def _json_array(text: str):
    text = re.sub(r"```(?:json)?|```", "", text or "").strip()
    a, b = text.find("["), text.rfind("]")
    if a >= 0 and b > a:
        text = text[a:b + 1]
    return json.loads(text)


def _tokens(text):
    return {x for x in re.findall(r"[a-z0-9]{3,}", (text or "").lower()) if x not in STOPWORDS}


def _relevance(query, title, creator=""):
    q = _tokens(query)
    t = _tokens((title or "") + " " + (creator or ""))
    if not q:
        return 0.0
    return len(q & t) / max(1, min(len(q), 5))


def _obviously_bad(title):
    low = (title or "").lower()
    return any(term in low for term in BANNED_TITLE_TERMS)


def _commons_wait():
    global _LAST_COMMONS
    now = time.monotonic()
    if now < _COMMONS_COOLDOWN_UNTIL:
        raise RuntimeError(f"Wikimedia cooldown active for {int(_COMMONS_COOLDOWN_UNTIL - now)}s")
    with _RATE_LOCK:
        now = time.monotonic()
        delay = COMMONS_MIN_INTERVAL - (now - _LAST_COMMONS)
        if delay > 0:
            time.sleep(delay)
        _LAST_COMMONS = time.monotonic()


def _record_commons_status(status):
    global _COMMONS_429S, _COMMONS_COOLDOWN_UNTIL
    if status == 429:
        _COMMONS_429S += 1
        if _COMMONS_429S >= 2:
            _COMMONS_COOLDOWN_UNTIL = time.monotonic() + COMMONS_COOLDOWN_SECONDS
            logger.warning(f"Wikimedia circuit breaker opened for {COMMONS_COOLDOWN_SECONDS}s")
    elif 200 <= status < 300:
        _COMMONS_429S = 0


def plan_scenes(script: str, target_minutes: int = 3, clip_seconds: int = 5):
    """
    Plan scenes using the local PydanticAI + Ollama structured-output agent first.

    Why this exists:
    qwen3:8b can reason well, but free-form JSON occasionally contains raw control
    characters or malformed JSON. The sidecar agent uses Ollama native JSON-schema
    constrained output plus Pydantic validation before MoneyPrinterTurbo receives
    any scene plan.

    Fallback order:
      1. PydanticAI structured scene planner
      2. Existing Ollama free-form planner
      3. Deterministic sentence-based planner
    """
    desired = max(
        8,
        min(
            180,
            math.ceil(max(target_minutes * 60, 60) / max(clip_seconds, 3)),
        ),
    )

    try:
        scenes = scene_planner_agent.plan_scenes(
            script=script,
            target_minutes=target_minutes,
            clip_seconds=clip_seconds,
            desired_scenes=desired,
        )
        if scenes:
            logger.info(
                f"PydanticAI scene planner validated {len(scenes)} scenes "
                f"with Ollama structured output"
            )
            return scenes
    except Exception as exc:
        logger.warning(
            "PydanticAI structured scene planner unavailable; "
            f"using legacy Ollama planner: {exc}"
        )

    # Compatibility fallback: preserve the existing working Ollama path.
    prompt = f"""You are the visual director of a documentary video.
Build about {desired} ordered scenes for a {target_minutes}-minute video.
Do not rewrite, shorten, summarize, or reorder narration.
Return ONLY a JSON array.
Each object: scene_number, narration, visual_search_query, alternative_search_query, estimated_duration.
Make queries short, literal, concrete, and searchable on Wikimedia Commons, Internet Archive, and Pexels.
For Bible/history prefer paintings, maps, archaeology, manuscripts, Jerusalem, deserts, shepherds,
tents, ruins, temples, church art, crosses, landscapes.
Avoid abstract queries such as "transition", "new season", "spiritual separation", "obedience", or "vision"
by themselves; convert abstract ideas into visible imagery.

SCRIPT:
{script}"""
    try:
        rows = _json_array(llm._generate_response(prompt))
        scenes = []
        for i, row in enumerate(rows[:desired], 1):
            if not isinstance(row, dict):
                continue
            scenes.append({
                "scene_number": i,
                "narration": str(row.get("narration", "")).strip(),
                "visual_search_query": str(row.get("visual_search_query", "")).strip(),
                "alternative_search_query": str(row.get("alternative_search_query", "")).strip(),
                "estimated_duration": max(
                    3,
                    float(row.get("estimated_duration") or clip_seconds),
                ),
            })
        if scenes:
            logger.info(
                f"Legacy Ollama scene planner returned {len(scenes)} scenes"
            )
            return scenes
    except Exception as exc:
        logger.warning(f"Ollama scene planner fallback: {exc}")

    logger.warning("Using deterministic sentence-based scene planner")
    parts = [
        x.strip()
        for x in re.split(r"(?<=[.!?])\s+", script)
        if x.strip()
    ]
    return [{
        "scene_number": i + 1,
        "narration": p,
        "visual_search_query": p[:90],
        "alternative_search_query": "biblical desert painting " + p[:60],
        "estimated_duration": clip_seconds,
    } for i, p in enumerate(parts[:desired])]

def _commons_search(query: str, limit: int = 6):
    _commons_wait()
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
        "iiurlwidth": 1280,
        "origin": "*",
    }
    r = _SESSION.get(COMMONS_API, params=params, timeout=40)
    _record_commons_status(r.status_code)
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages") or {}
    out = []
    for page in pages.values():
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            continue
        mime = str(info.get("mime", "")).lower()
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            continue
        meta = info.get("extmetadata") or {}
        title = str(page.get("title", ""))
        if _obviously_bad(title):
            continue
        creator = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", ""))
        score = _relevance(query, title, creator)
        if score < 0.12 and len(_tokens(query)) >= 2:
            continue
        url = info.get("thumburl") or info.get("url")
        if url:
            out.append({
                "provider": "Wikimedia Commons",
                "url": url,
                "page": info.get("descriptionurl", ""),
                "license": (meta.get("LicenseShortName") or {}).get("value", ""),
                "creator": creator,
                "title": title,
                "score": score,
            })
    return sorted(out, key=lambda x: x.get("score", 0), reverse=True)


def _archive_search(query: str, limit: int = 5):
    params = {
        "q": f"({query}) AND (mediatype:image OR mediatype:movies)",
        "fl[]": ["identifier", "title", "mediatype"],
        "rows": limit,
        "output": "json",
    }
    r = _SESSION.get(IA_SEARCH, params=params, timeout=40)
    r.raise_for_status()
    out = []
    for doc in r.json().get("response", {}).get("docs", []):
        ident = doc.get("identifier")
        title = str(doc.get("title", ident or ""))
        if not ident or _obviously_bad(title):
            continue
        score = _relevance(query, title)
        if score < 0.20:
            continue
        try:
            meta = _SESSION.get(IA_META.format(ident), timeout=30).json()
        except Exception:
            continue
        md = meta.get("metadata") or {}
        creator = str(md.get("creator", ""))
        if _relevance(query, title, creator) < 0.20:
            continue
        for f in meta.get("files", []):
            name = str(f.get("name", ""))
            low = name.lower()
            if not low.endswith((".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov")):
                continue
            if low.endswith(("_thumb.jpg", "__ia_thumb.jpg")):
                continue
            try:
                size = int(f.get("size") or 0)
            except Exception:
                size = 0
            if size and size > 180 * 1024 * 1024:
                continue
            out.append({
                "provider": "Internet Archive",
                "url": f"https://archive.org/download/{quote(ident)}/{quote(name)}",
                "page": f"https://archive.org/details/{quote(ident)}",
                "license": str(md.get("licenseurl", "")),
                "creator": creator,
                "title": title,
                "score": score,
            })
            break
    return sorted(out, key=lambda x: x.get("score", 0), reverse=True)


def _pexels_key():
    value = config.app.get("pexels_api_keys", []) or []
    if isinstance(value, (list, tuple)):
        return next((str(x).strip() for x in value if str(x).strip()), "")
    raw = str(value).strip()
    if not raw:
        return ""
    for sep in [",", ";", "\n"]:
        raw = raw.replace(sep, " ")
    return next((x.strip().strip("[]'\\\"") for x in raw.split() if x.strip()), "")



def _sanitize_pexels_query(query: str, max_words: int = 14, max_chars: int = 120) -> str:
    """
    Convert narration-like text into a compact Pexels-safe search query.

    Removes control characters, smart quotes and sentence punctuation, collapses
    whitespace, and caps query length. This protects the Pexels API from raw
    narration such as multi-line dialogue with curly quotes.
    """
    text = unicodedata.normalize("NFKC", str(query or ""))
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = "".join(ch if (ch.isprintable() and ch not in "\r\n\t") else " " for ch in text)
    text = re.sub(r"[\u0000-\u001f\u007f-\u009f]+", " ", text)
    text = re.sub(r"[\"“”‘’`]+", " ", text)
    text = re.sub(r"[^\w\s'-]+", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()

    words = text.split()
    if len(words) > max_words:
        words = words[:max_words]
    text = " ".join(words)

    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0].strip()

    return text


def _pexels_search(query: str, limit: int = 8):
    key = _pexels_key()
    if not key:
        return []

    safe_query = _sanitize_pexels_query(query)
    if not safe_query:
        logger.warning("Pexels search skipped because sanitized query was empty")
        return []

    if safe_query != str(query or "").strip():
        logger.debug(f"Pexels query sanitized: {safe_query!r}")

    try:
        r = _SESSION.get(
            PEXELS_VIDEO_SEARCH,
            params={"query": safe_query, "per_page": min(15, limit), "orientation": "landscape"},
            headers={"Authorization": key, "User-Agent": USER_AGENT},
            timeout=35,
        )
        if r.status_code == 401:
            logger.warning("Pexels API key rejected (401); skipping Pexels fallback")
            return []
        r.raise_for_status()
        out = []
        for row in r.json().get("videos", []):
            files = row.get("video_files") or []
            files = sorted(files, key=lambda x: (abs((x.get("width") or 0) - 1920), -(x.get("width") or 0)))
            f = next((x for x in files if x.get("link")), None)
            if not f:
                continue
            out.append({
                "provider": "Pexels",
                "url": f["link"],
                "page": row.get("url", ""),
                "license": "Pexels License",
                "creator": (row.get("user") or {}).get("name", ""),
                "title": safe_query,
                "score": 0.50,
            })
        return out
    except Exception as exc:
        logger.warning(f"Pexels fallback search failed: {exc}")
        return []


def _download(item: dict, cache_dir: Path):
    url = item["url"]
    digest = hashlib.sha256(url.encode()).hexdigest()
    suffix = Path(url.split("?")[0]).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov"}:
        suffix = ".mp4" if item.get("provider") == "Pexels" else ".jpg"
    path = cache_dir / f"{digest}{suffix}"
    if path.exists() and path.stat().st_size > 4096:
        return path
    temp = path.with_suffix(path.suffix + ".part")
    try:
        if item.get("provider") == "Wikimedia Commons":
            _commons_wait()
        r = _SESSION.get(url, timeout=120, stream=True)
        if item.get("provider") == "Wikimedia Commons":
            _record_commons_status(r.status_code)
        r.raise_for_status()
        with temp.open("wb") as h:
            for chunk in r.iter_content(262144):
                if chunk:
                    h.write(chunk)
        if not temp.exists() or temp.stat().st_size < 4096:
            raise ValueError("downloaded media was too small")
        temp.replace(path)
        return path
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _make_motion_clip(image_path: Path, duration: int, scene_number: int):
    out = image_path.with_name(f"scene-{scene_number:03d}-motion.mp4")
    frames = max(75, int(duration * 30))
    zoom = "min(zoom+0.0007,1.10)" if scene_number % 2 else "min(zoom+0.0005,1.08)"
    vf = (
        f"scale=2200:-2,zoompan=z='{zoom}':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080:fps=30,"
        "format=yuv420p"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", str(image_path), "-vf", vf,
         "-t", str(max(3, duration)), "-an", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", str(out)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return out


def _storyboard(output_dir, scenes, records):
    by = {r.get("scene_number"): r for r in records}
    cards = []
    for sc in scenes:
        r = by.get(sc.get("scene_number"), {})
        cards.append(
            f"<article><h3>Scene {sc.get('scene_number')}</h3>"
            f"<p><b>Search:</b> {html.escape(sc.get('visual_search_query',''))}</p>"
            f"<p><b>Selected:</b> {html.escape(r.get('title','MISSING'))}</p>"
            f"<p><b>Source:</b> {html.escape(r.get('provider',''))}</p></article>"
        )
    page = (
        "<!doctype html><meta charset='utf-8'><style>"
        "body{font-family:Segoe UI;background:#0d1117;color:#eee;padding:24px}"
        "main{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}"
        "article{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:14px}"
        "b{color:#58a6ff}</style><h1>Ollama Director Storyboard</h1><main>"
        + "".join(cards) + "</main>"
    )
    (output_dir / "storyboard.html").write_text(page, encoding="utf-8")


def download_for_script(task_id: str, script: str, target_minutes: int, clip_seconds: int):
    task_dir = Path(utils.task_dir(task_id))

    # Metadata/storyboard stay with the task.
    output_dir = task_dir / "ollama_auto_media"
    output_dir.mkdir(parents=True, exist_ok=True)

    # IMPORTANT: video.preprocess_video intentionally rejects arbitrary local
    # paths. Automatic media therefore lives under the trusted local-videos root.
    # This fixes "path is outside the allowed directory" without weakening the
    # security check in video.py.
    safe_media_dir = Path("storage/local_videos") / "ollama_auto_media" / str(task_id)
    safe_media_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = Path("storage/cache/ollama_auto_media")
    cache_dir.mkdir(parents=True, exist_ok=True)

    scenes = plan_scenes(script, target_minutes, clip_seconds)
    (output_dir / "scene_plan.json").write_text(
        json.dumps(scenes, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    used = set()
    records = []
    materials = []

    pexels_available = bool(_pexels_key())
    if pexels_available:
        logger.info("Pexels fallback is configured and available")
    else:
        logger.info("Pexels fallback not configured; using Wikimedia + Internet Archive only")

    for scene in scenes:
        queries = [scene.get("visual_search_query", ""), scene.get("alternative_search_query", "")]
        candidates = []

        for query in queries:
            if not query:
                continue
            try:
                candidates.extend(_commons_search(query, 6))
            except Exception as exc:
                logger.warning(f"Wikimedia Commons search failed for {query!r}: {exc}")

            try:
                candidates.extend(_archive_search(query, 5))
            except Exception as exc:
                logger.warning(f"Internet Archive search failed for {query!r}: {exc}")

            if pexels_available and len(candidates) < 3:
                candidates.extend(_pexels_search(query, 8))

        unique = []
        seen = set()
        for c in candidates:
            if not c.get("url") or c["url"] in seen or c["url"] in used:
                continue
            seen.add(c["url"])
            unique.append(c)

        unique.sort(key=lambda x: x.get("score", 0), reverse=True)

        chosen = None
        for item in unique:
            try:
                source = _download(item, cache_dir)
                used.add(item["url"])
                chosen = (item, source)
                break
            except Exception as exc:
                logger.warning(f"{item.get('provider')} media download failed: {exc}")

        if not chosen and pexels_available:
            for query in queries:
                for item in _pexels_search(query, 10):
                    if item["url"] in used:
                        continue
                    try:
                        source = _download(item, cache_dir)
                        used.add(item["url"])
                        chosen = (item, source)
                        break
                    except Exception as exc:
                        logger.warning(f"Pexels media download failed: {exc}")
                if chosen:
                    break

        if not chosen:
            logger.warning(f"No usable media found for scene {scene['scene_number']}")
            continue

        item, source = chosen
        dest = safe_media_dir / f"scene-{scene['scene_number']:03d}{source.suffix.lower()}"
        shutil.copy2(source, dest)

        dur = max(3, int(scene.get("estimated_duration") or clip_seconds))
        material_path = dest
        if dest.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            try:
                material_path = _make_motion_clip(dest, dur, scene["scene_number"])
            except Exception as exc:
                logger.warning(f"Ken Burns failed: {exc}")

        materials.append(MaterialInfo(
            provider="ollama_auto_media",
            url=str(material_path),
            duration=dur,
            source_info={
                "search_term": scene.get("visual_search_query", ""),
                "source_page": item.get("page", ""),
                "creator": item.get("creator", ""),
            },
        ))

        records.append({
            **scene,
            "local_file": str(material_path),
            "provider": item.get("provider", ""),
            "source_url": item.get("page", ""),
            "license": item.get("license", ""),
            "creator": item.get("creator", ""),
            "title": item.get("title", ""),
        })

    coverage = len(records) / max(1, len(scenes))
    logger.info(f"Auto-media coverage: {len(records)}/{len(scenes)} scenes ({coverage:.0%})")

    (output_dir / "coverage.json").write_text(
        json.dumps({"found": len(records), "planned": len(scenes), "coverage": coverage}, indent=2),
        encoding="utf-8",
    )
    (output_dir / "attribution.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output_dir / "ATTRIBUTION.md").write_text(
        "\n".join(
            f"- Scene {r['scene_number']}: {r['title']} — {r['provider']} — {r['license']} — {r['source_url']}"
            for r in records
        ),
        encoding="utf-8",
    )
    _storyboard(output_dir, scenes, records)

    if coverage < 0.70:
        raise RuntimeError(
            f"Automatic media coverage too low: {len(records)}/{len(scenes)} scenes ({coverage:.0%}). "
            "Configure a Pexels API key or retry after the Wikimedia cooldown."
        )

    if not materials:
        return [], scenes

    processed = video.preprocess_video(materials=materials, clip_duration=clip_seconds)
    return [m.url for m in processed], scenes
