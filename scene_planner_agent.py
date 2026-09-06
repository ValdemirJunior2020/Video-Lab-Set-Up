import time
from typing import Any

import requests
from loguru import logger

from app.config import config

_DEFAULT_URL = "http://scene-planner:4130"
_SESSION = requests.Session()


def _app_config(key: str, default: Any):
    try:
        return config.app.get(key, default)
    except Exception:
        return default


def enabled() -> bool:
    value = _app_config("pydantic_scene_planner_enabled", True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def base_url() -> str:
    value = _app_config("pydantic_scene_planner_url", _DEFAULT_URL)
    return str(value or _DEFAULT_URL).rstrip("/")


def timeout_seconds() -> int:
    try:
        return max(
            30,
            int(_app_config("pydantic_scene_planner_timeout_seconds", 300)),
        )
    except Exception:
        return 300


def retries() -> int:
    try:
        return max(
            1,
            min(5, int(_app_config("pydantic_scene_planner_retries", 3))),
        )
    except Exception:
        return 3


def health(timeout: int = 5) -> bool:
    if not enabled():
        return False
    try:
        response = _SESSION.get(base_url() + "/health", timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False


def _normalize_scene(row: dict, index: int, clip_seconds: int) -> dict:
    narration = str(row.get("narration", "")).strip()
    query = str(row.get("visual_search_query", "")).strip()
    alt = str(row.get("alternative_search_query", "")).strip()
    try:
        duration = max(
            3.0,
            float(row.get("estimated_duration") or clip_seconds),
        )
    except Exception:
        duration = float(max(3, clip_seconds))

    if not narration:
        raise ValueError(f"scene {index} has empty narration")
    if not query:
        raise ValueError(f"scene {index} has empty visual_search_query")
    if not alt:
        alt = query

    return {
        "scene_number": index,
        "narration": narration,
        "visual_search_query": query,
        "alternative_search_query": alt,
        "estimated_duration": duration,
    }


def plan_scenes(
    script: str,
    target_minutes: int,
    clip_seconds: int,
    desired_scenes: int,
) -> list[dict]:
    if not enabled():
        raise RuntimeError("PydanticAI scene planner is disabled")

    script = str(script or "").strip()
    if not script:
        raise ValueError("script is empty")

    payload = {
        "script": script,
        "target_minutes": int(target_minutes),
        "clip_seconds": int(clip_seconds),
        "desired_scenes": int(desired_scenes),
    }

    last_error = None
    for attempt in range(1, retries() + 1):
        try:
            logger.info(
                f"PydanticAI scene planner request {attempt}/{retries()} "
                f"for about {desired_scenes} scenes"
            )
            response = _SESSION.post(
                base_url() + "/v1/plan",
                json=payload,
                timeout=timeout_seconds(),
            )
            response.raise_for_status()
            body = response.json()
            rows = body.get("scenes")
            if not isinstance(rows, list) or not rows:
                raise ValueError("scene planner returned no scenes")

            scenes = [
                _normalize_scene(row, i, clip_seconds)
                for i, row in enumerate(rows[:desired_scenes], 1)
                if isinstance(row, dict)
            ]
            if not scenes:
                raise ValueError("scene planner returned no valid scenes")

            logger.info(
                f"PydanticAI scene planner accepted {len(scenes)} "
                f"validated scenes (backend={body.get('backend', 'unknown')})"
            )
            return scenes
        except Exception as exc:
            last_error = exc
            logger.warning(
                f"PydanticAI scene planner attempt {attempt} failed: {exc}"
            )
            if attempt < retries():
                time.sleep(min(2 ** (attempt - 1), 4))

    raise RuntimeError(
        f"PydanticAI scene planner failed after {retries()} attempts: "
        f"{last_error}"
    )
