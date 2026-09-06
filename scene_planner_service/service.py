import os
import re
import time
from typing import Annotated

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.output import NativeOutput
from pydantic_ai.providers.ollama import OllamaProvider

app = FastAPI(
    title="MoneyPrinterTurbo PydanticAI Scene Planner",
    version="9.0",
)

OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "http://host.docker.internal:11434/v1",
)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
MAX_RETRIES = max(1, min(5, int(os.getenv("SCENE_AGENT_RETRIES", "3"))))


class Scene(BaseModel):
    scene_number: int = Field(ge=1, le=500)
    narration: str = Field(min_length=1, max_length=6000)
    visual_search_query: str = Field(min_length=2, max_length=220)
    alternative_search_query: str = Field(min_length=2, max_length=220)
    estimated_duration: float = Field(ge=3, le=60)

    @field_validator(
        "narration",
        "visual_search_query",
        "alternative_search_query",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value):
        return str(value or "").strip()


class ScenePlan(BaseModel):
    scenes: list[Scene] = Field(min_length=1, max_length=180)


class PlanRequest(BaseModel):
    script: str = Field(min_length=1, max_length=200000)
    target_minutes: int = Field(default=3, ge=1, le=10)
    clip_seconds: int = Field(default=5, ge=1, le=30)
    desired_scenes: int = Field(default=36, ge=1, le=180)


model = OllamaModel(
    OLLAMA_MODEL,
    provider=OllamaProvider(base_url=OLLAMA_BASE_URL),
)

agent = Agent(
    model,
    output_type=NativeOutput(ScenePlan),
    instructions=(
        "You are the visual director for documentary videos. "
        "Your final answer MUST satisfy the supplied native JSON schema. "
        "Never emit markdown, commentary, code fences, or reasoning. "
        "Preserve narration wording and chronological order. "
        "Search queries must describe things a stock-media or public-domain "
        "search engine can literally find."
    ),
)


def _prompt(req: PlanRequest, retry_note: str = "") -> str:
    return f"""
Create approximately {req.desired_scenes} ordered scenes for a
{req.target_minutes}-minute documentary.

STRICT RULES:
1. Keep the source narration in its original order.
2. Do not invent events or facts not present in the script.
3. Do not put JSON text inside string fields.
4. visual_search_query must be short, concrete, visual, and searchable.
5. alternative_search_query must be a genuinely useful second search.
6. estimated_duration should normally be around {max(3, req.clip_seconds)} seconds.
7. For Bible/history topics prefer useful literal visuals such as paintings,
   maps, archaeology, manuscripts, Jerusalem, deserts, shepherds, tents,
   ruins, temples, landscapes, church art, historical reconstructions.
8. Convert abstract ideas into visible imagery. Do not search for bare concepts
   like "faith", "obedience", "transition", "destiny", or "new season".
9. Produce no more than {req.desired_scenes} scenes.
10. Return only the schema-constrained result.

{retry_note}

SOURCE SCRIPT:
{req.script}
""".strip()


def _word_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", (text or "").lower()))


def _basic_quality_check(plan: ScenePlan, req: PlanRequest) -> None:
    if not plan.scenes:
        raise ValueError("no scenes returned")

    source_tokens = _word_tokens(req.script)
    narration_tokens = _word_tokens(" ".join(s.narration for s in plan.scenes))
    if source_tokens:
        overlap = len(source_tokens & narration_tokens) / len(source_tokens)
        # This is intentionally permissive: the goal is catching unrelated or
        # hallucinated plans, not requiring a byte-for-byte segmentation.
        if overlap < 0.45:
            raise ValueError(
                f"scene narration appears unrelated to source script "
                f"(token overlap {overlap:.2f})"
            )

    for scene in plan.scenes:
        if len(scene.visual_search_query.split()) > 24:
            raise ValueError(
                f"scene {scene.scene_number} visual query is too long"
            )


@app.get("/health")
def health():
    return {
        "ok": True,
        "backend": "pydantic_ai_native_output",
        "model": OLLAMA_MODEL,
        "ollama_base_url": OLLAMA_BASE_URL,
        "max_retries": MAX_RETRIES,
    }


@app.post("/v1/plan")
def plan(req: PlanRequest):
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        retry_note = ""
        if last_error:
            retry_note = (
                "The previous attempt failed validation. Correct the problem "
                f"without changing the source facts. Validation error: {last_error}"
            )

        try:
            result = agent.run_sync(_prompt(req, retry_note))
            plan_obj = result.output
            _basic_quality_check(plan_obj, req)

            scenes = []
            for i, scene in enumerate(
                plan_obj.scenes[: req.desired_scenes],
                start=1,
            ):
                item = scene.model_dump()
                item["scene_number"] = i
                item["estimated_duration"] = max(
                    3.0,
                    float(item["estimated_duration"]),
                )
                scenes.append(item)

            return {
                "backend": "pydantic_ai_native_output",
                "model": OLLAMA_MODEL,
                "attempt": attempt,
                "validated": True,
                "scenes": scenes,
            }
        except Exception as exc:
            last_error = str(exc)
            if attempt < MAX_RETRIES:
                time.sleep(min(2 ** (attempt - 1), 4))

    raise HTTPException(
        status_code=502,
        detail=(
            "PydanticAI/Ollama could not produce a validated scene plan "
            f"after {MAX_RETRIES} attempts: {last_error}"
        ),
    )
