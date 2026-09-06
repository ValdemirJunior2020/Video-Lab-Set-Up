import ast
import subprocess
import sys
import time
from pathlib import Path

import requests
import tomllib

ROOT = Path(sys.argv[1]).resolve()
CONFIG = ROOT / "config.toml"


def ok(msg):
    print(f"[PASS] {msg}")


def fail(msg):
    print(f"[FAIL] {msg}")
    raise SystemExit(1)


def run(cmd, timeout=180):
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if p.returncode != 0:
        print(p.stdout)
        fail("Command failed: " + " ".join(cmd))
    return p


for rel in ["webui/Main.py", "app/services/task.py", "app/services/emotional_tts.py", "chatterbox_service/chatterbox_service.py"]:
    ast.parse((ROOT / rel).read_text(encoding="utf-8"), filename=rel)
ok("Modified Python syntax")

run(["docker", "exec", "moneyprinterturbo-webui", "python", "-m", "compileall", "-q", "/MoneyPrinterTurbo/app", "/MoneyPrinterTurbo/webui"])
ok("compileall inside Docker")

run(["docker", "exec", "moneyprinterturbo-webui", "python", "-c", "import requests;r=requests.get('http://host.docker.internal:11434/api/tags',timeout=10);r.raise_for_status();print('OK')"], 30)
ok("Ollama reachable")

cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8-sig"))
keys = cfg.get("app", {}).get("pexels_api_keys", [])
key = keys[0] if isinstance(keys, list) and keys else ""
if not key:
    fail("Pexels key missing")
r = requests.get("https://api.pexels.com/videos/search", params={"query": "desert landscape", "per_page": 1}, headers={"Authorization": key}, timeout=30)
if r.status_code != 200:
    fail(f"Pexels API HTTP {r.status_code}")
ok("Pexels API authentication")

deadline = time.time() + 180
last = None
while time.time() < deadline:
    try:
        rr = requests.get("http://127.0.0.1:4123/health", timeout=5)
        if rr.status_code == 200:
            break
        last = rr.status_code
    except Exception as exc:
        last = exc
    time.sleep(3)
else:
    fail(f"Chatterbox health not ready: {last}")
ok("Chatterbox service health")

rr = requests.post(
    "http://127.0.0.1:4123/v1/tts",
    json={"text": "Abraham looked toward the horizon. The promise was still before him. He chose to trust.", "profile": "sermon"},
    timeout=1200,
)
if rr.status_code != 200:
    fail(f"Chatterbox synthesis HTTP {rr.status_code}: {rr.text[-500:]}")
wav = ROOT / "V8_CHATTERBOX_TEST.wav"
wav.write_bytes(rr.content)
if wav.stat().st_size < 10000:
    fail("Chatterbox test audio too small")
ok("Chatterbox real synthesis")

run(["docker", "exec", "moneyprinterturbo-webui", "python", "-c", "from app.services import emotional_tts;assert emotional_tts.enabled();assert emotional_tts.health();print('OK')"], 30)
ok("MoneyPrinterTurbo -> Chatterbox connection")

run(["docker", "exec", "moneyprinterturbo-webui", "python", "-c", "from app.services import local_tts;assert local_tts.synthesize('Fallback narration test.', '/tmp/v8-piper.mp3');print('OK')"], 180)
ok("Piper fallback synthesis")

deadline = time.time() + 120
while time.time() < deadline:
    try:
        if requests.get("http://127.0.0.1:8501", timeout=5).status_code == 200:
            break
    except Exception:
        pass
    time.sleep(2)
else:
    fail("WebUI not ready")
ok("WebUI HTTP 200")

from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    page.goto("http://127.0.0.1:8501", wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(10000)
    text = page.locator("body").inner_text(timeout=30000)
    for frame in page.frames:
        try:
            text += "\n" + frame.locator("body").inner_text(timeout=2000)
        except Exception:
            pass
    for token in ["Traceback", "grouped selectbox options must be unique", "Please Select a Valid Video Source", "SyntaxError"]:
        if token in text:
            browser.close()
            fail("Microsoft Playwright found visible error: " + token)
    for expected in ["MoneyPrinterTurbo", "Pexels", "Ollama Director"]:
        if expected not in text:
            browser.close()
            fail("UI missing: " + expected)
    page.screenshot(path=str(ROOT / "V8_PLAYWRIGHT_PASS.png"), full_page=True)
    browser.close()
ok("Microsoft Playwright browser smoke test")

print("============================================================")
print(" ALL V8 TESTS PASSED")
print(" Ollama PASS | Pexels PASS | Chatterbox PASS | Piper PASS | Playwright PASS")
print("============================================================")
