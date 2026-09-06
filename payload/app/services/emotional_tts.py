import re
import subprocess
from pathlib import Path

import requests
from loguru import logger
from app.config import config

DEFAULT_URL = "http://chatterbox:4123"


def _cfg(name, default):
    try:
        return config.app.get(name, default)
    except Exception:
        return default


def enabled():
    value = _cfg("expressive_tts_enabled", True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def profile():
    return str(_cfg("expressive_tts_profile", "sermon") or "sermon").strip().lower()


def base_url():
    return str(_cfg("chatterbox_base_url", DEFAULT_URL) or DEFAULT_URL).rstrip("/")


def health(timeout=4):
    try:
        return requests.get(base_url() + "/health", timeout=timeout).status_code == 200
    except Exception:
        return False


def _chunks(text, max_chars=850):
    paragraphs = [x.strip() for x in re.split(r"\n\s*\n+", text or "") if x.strip()]
    chunks = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            chunks.append(paragraph)
            continue
        current = ""
        for sentence in [x.strip() for x in re.split(r"(?<=[.!?])\s+", paragraph) if x.strip()]:
            candidate = (current + " " + sentence).strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = sentence
            else:
                current = candidate
        if current:
            chunks.append(current)
    return chunks or [str(text or "").strip()]


def synthesize(text, output_file):
    if not enabled():
        logger.info("expressive Chatterbox narration disabled")
        return False
    chunks = [c for c in _chunks(text) if c]
    if not chunks:
        return False
    out = Path(output_file)
    work = out.parent / ".chatterbox-v8"
    work.mkdir(parents=True, exist_ok=True)
    wavs = []
    try:
        logger.info(f"Chatterbox expressive narration start: profile={profile()}, chunks={len(chunks)}")
        for index, chunk in enumerate(chunks, 1):
            r = requests.post(
                base_url() + "/v1/tts",
                json={"text": chunk, "profile": profile()},
                timeout=max(600, len(chunk) * 3),
            )
            r.raise_for_status()
            wav = work / f"chunk-{index:04d}.wav"
            wav.write_bytes(r.content)
            if wav.stat().st_size < 2048:
                raise RuntimeError(f"Chatterbox chunk {index} too small")
            wavs.append(wav)
            logger.info(f"Chatterbox chunk {index}/{len(chunks)} complete")

        concat = work / "concat.txt"
        concat.write_text("\n".join(f"file '{p.as_posix()}'" for p in wavs), encoding="utf-8")
        p = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-codec:a", "libmp3lame", "-q:a", "2", str(out)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=1200,
        )
        if p.returncode or not out.exists() or out.stat().st_size < 2048:
            raise RuntimeError("ffmpeg Chatterbox merge failed: " + p.stderr.decode(errors="ignore")[-1000:])
        logger.info("Chatterbox expressive narration completed successfully")
        return True
    except Exception as exc:
        logger.warning(f"Chatterbox expressive narration failed: {exc}")
        return False
    finally:
        try:
            for item in wavs:
                item.unlink(missing_ok=True)
            (work / "concat.txt").unlink(missing_ok=True)
            work.rmdir()
        except Exception:
            pass
