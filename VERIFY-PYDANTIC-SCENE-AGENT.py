import ast
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(sys.argv[1]).resolve()


def passed(message):
    print("[PASS]", message)


def failed(message):
    print("[FAIL]", message)
    raise SystemExit(1)


def run(cmd, timeout=180):
    p = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    if p.returncode != 0:
        print(p.stdout)
        failed("Command failed: " + " ".join(cmd))
    return p


# 1. Python syntax.
for rel in [
    "app/services/auto_media.py",
    "app/services/scene_planner_agent.py",
    "scene_planner_service/service.py",
]:
    ast.parse((ROOT / rel).read_text(encoding="utf-8"), filename=rel)
passed("Modified Python syntax")

# 1b. Media safety + Pexels sanitization regression checks.
auto_text = (ROOT / "app/services/auto_media.py").read_text(encoding="utf-8")
if 'Path("storage/local_videos") / "ollama_auto_media" / str(task_id)' not in auto_text:
    failed("Auto-media is not using the trusted storage/local_videos directory")
if "_sanitize_pexels_query" not in auto_text:
    failed("Pexels query sanitizer is missing")
passed("Safe auto-media directory + Pexels sanitizer present")

run([
    "docker",
    "exec",
    "moneyprinterturbo-webui",
    "python",
    "-c",
    (
        "from app.services.auto_media import _sanitize_pexels_query; "
        "q=_sanitize_pexels_query('He told Lot, “Let there be no strife between you and me.”\\n\\nThen Abraham gave Lot the opportunity'); "
        "assert '\\\\n' not in q and '“' not in q and '”' not in q and len(q)<=120; "
        "print(q)"
    ),
], timeout=30)
passed("Pexels narration-query sanitization regression test")

# 2. Compose and containers.
run(["docker", "compose", "config"], timeout=30)
passed("Docker Compose config")

# Wait for scene planner.
deadline = time.time() + 120
last = None
while time.time() < deadline:
    try:
        r = requests.get("http://127.0.0.1:4130/health", timeout=5)
        if r.status_code == 200:
            info = r.json()
            if info.get("backend") != "pydantic_ai_native_output":
                failed("Unexpected scene planner backend")
            break
        last = r.status_code
    except Exception as exc:
        last = exc
    time.sleep(2)
else:
    failed(f"PydanticAI scene planner health failed: {last}")
passed("PydanticAI scene planner health")

# 3. REAL qwen3:8b schema-constrained scene plan.
sample_script = (
    "Abraham left his homeland and traveled with his family. "
    "He crossed dry lands and lived in tents. "
    "At night he looked toward the stars and remembered the promise."
)
r = requests.post(
    "http://127.0.0.1:4130/v1/plan",
    json={
        "script": sample_script,
        "target_minutes": 1,
        "clip_seconds": 5,
        "desired_scenes": 8,
    },
    timeout=600,
)
if r.status_code != 200:
    failed(f"Real structured scene plan HTTP {r.status_code}: {r.text[-1200:]}")
body = r.json()
if body.get("backend") != "pydantic_ai_native_output":
    failed("Structured-output backend marker missing")
if body.get("validated") is not True:
    failed("Pydantic validation marker missing")
scenes = body.get("scenes")
if not isinstance(scenes, list) or not scenes:
    failed("No validated scenes returned")
required = {
    "scene_number",
    "narration",
    "visual_search_query",
    "alternative_search_query",
    "estimated_duration",
}
for index, scene in enumerate(scenes, 1):
    missing = required - set(scene)
    if missing:
        failed(f"Scene {index} missing fields: {sorted(missing)}")
passed(f"Real Ollama structured output: {len(scenes)} validated scenes")

# 4. MoneyPrinterTurbo client -> sidecar.
run([
    "docker",
    "exec",
    "moneyprinterturbo-webui",
    "python",
    "-c",
    (
        "from app.services import scene_planner_agent as s; "
        "x=s.plan_scenes('A traveler crossed the desert and reached an ancient city.',1,5,8); "
        "assert x and x[0]['visual_search_query']; "
        "print(len(x))"
    ),
], timeout=600)
passed("MoneyPrinterTurbo -> PydanticAI scene planner connection")

# 5. Pexels key and API without ever printing the key.
try:
    import tomllib
    cfg = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8-sig"))
    keys = cfg.get("app", {}).get("pexels_api_keys", [])
    key = keys[0] if isinstance(keys, list) and keys else ""
except Exception as exc:
    failed(f"Could not read local Pexels configuration: {exc}")

if not key:
    failed("Pexels API key is not configured")

r = requests.get(
    "https://api.pexels.com/videos/search",
    params={"query": "desert landscape", "per_page": 1},
    headers={"Authorization": key},
    timeout=30,
)
if r.status_code != 200:
    failed(f"Pexels API returned HTTP {r.status_code}")
passed("Pexels API")

# 6. Existing Chatterbox service remains alive.
try:
    r = requests.get("http://127.0.0.1:4123/health", timeout=10)
    if r.status_code != 200:
        failed(f"Chatterbox health HTTP {r.status_code}")
except Exception as exc:
    failed(f"Chatterbox health failed: {exc}")
passed("Chatterbox service preserved")

# 7. WebUI.
deadline = time.time() + 120
while time.time() < deadline:
    try:
        r = requests.get("http://127.0.0.1:8501", timeout=5)
        if r.status_code == 200:
            break
    except Exception:
        pass
    time.sleep(2)
else:
    failed("MoneyPrinterTurbo WebUI did not become ready")
passed("WebUI HTTP 200")

# 8. Microsoft Playwright browser gate.
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    console_errors = []

    def on_console(msg):
        if msg.type == "error":
            console_errors.append(msg.text)

    page.on("console", on_console)
    page.goto(
        "http://127.0.0.1:8501",
        wait_until="domcontentloaded",
        timeout=90000,
    )
    page.wait_for_timeout(10000)

    text = page.locator("body").inner_text(timeout=30000)
    for frame in page.frames:
        try:
            text += "\n" + frame.locator("body").inner_text(timeout=2000)
        except Exception:
            pass

    forbidden = [
        "Traceback",
        "SyntaxError",
        "grouped selectbox options must be unique",
        "Please Select a Valid Video Source",
    ]
    for token in forbidden:
        if token in text:
            browser.close()
            failed(f"Microsoft Playwright saw visible error: {token}")

    if "MoneyPrinterTurbo" not in text:
        browser.close()
        failed("Microsoft Playwright could not find MoneyPrinterTurbo UI")

    screenshot = ROOT / "V9_PLAYWRIGHT_PASS.png"
    page.screenshot(path=str(screenshot), full_page=True)
    browser.close()

passed("Microsoft Playwright Chromium browser gate")

print()
print("============================================================")
print(" ALL V9 TESTS PASSED")
print(" PydanticAI structured scene planner .... PASS")
print(" Ollama qwen3:8b native JSON schema ..... PASS")
print(" Pexels ................................ PASS")
print(" Chatterbox preserved ................... PASS")
print(" Microsoft Playwright ................... PASS")
print("============================================================")
