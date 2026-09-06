
import ast
import subprocess
import sys
import time
from pathlib import Path
import requests

ROOT = Path(sys.argv[1]).resolve()
CONFIG = ROOT / "config.toml"
MAIN = ROOT / "webui" / "Main.py"

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

try:
    ast.parse(MAIN.read_text(encoding="utf-8"))
    ok("webui/Main.py syntax")
except Exception as exc:
    fail(f"Main.py syntax: {exc}")

run(["docker","exec","moneyprinterturbo-webui","python","-m","compileall","-q","/MoneyPrinterTurbo/app","/MoneyPrinterTurbo/webui"])
ok("compileall inside Docker")

run(["docker","exec","moneyprinterturbo-webui","python","-c",
     "import requests; r=requests.get('http://host.docker.internal:11434/api/tags',timeout=10); r.raise_for_status(); print('OK')"], timeout=30)
ok("Ollama reachable from Docker")

run(["docker","exec","moneyprinterturbo-webui","python","-c","from app.services import auto_media; print('OK')"], timeout=30)
ok("Auto Media import")

run(["docker","exec","moneyprinterturbo-webui","sh","-lc","command -v piper >/dev/null"], timeout=30)
run(["docker","exec","moneyprinterturbo-webui","python","-c",
     "from app.services import local_tts; assert local_tts.synthesize('Local narration test.', '/tmp/mpt-v7-test.mp3'); print('OK')"], timeout=180)
run(["docker","exec","moneyprinterturbo-webui","ffprobe","-v","error","-show_entries","format=duration",
     "-of","default=noprint_wrappers=1:nokey=1","/tmp/mpt-v7-test.mp3"], timeout=30)
ok("Local Piper TTS")

try:
    import tomllib
    cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8-sig"))
    keys = cfg.get("app", {}).get("pexels_api_keys", [])
    key = keys[0] if isinstance(keys, list) and keys else ""
except Exception as exc:
    fail(f"Read Pexels config: {exc}")
if not key:
    fail("Pexels key missing")
r = requests.get("https://api.pexels.com/videos/search",
                 params={"query":"desert landscape","per_page":1},
                 headers={"Authorization":key}, timeout=30)
if r.status_code != 200:
    fail(f"Pexels API HTTP {r.status_code}")
ok("Pexels API key accepted")

deadline = time.time() + 90
last = None
while time.time() < deadline:
    try:
        rr = requests.get("http://127.0.0.1:8501", timeout=5)
        if rr.status_code == 200:
            break
        last = rr.status_code
    except Exception as exc:
        last = exc
    time.sleep(2)
else:
    fail(f"WebUI not ready: {last}")
ok("WebUI HTTP 200")

from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width":1440,"height":1000})
    page.goto("http://127.0.0.1:8501", wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(8000)
    combined = page.locator("body").inner_text(timeout=30000)
    for frame in page.frames:
        try:
            combined += "\n" + frame.locator("body").inner_text(timeout=2000)
        except Exception:
            pass
    for token in ["Traceback", "grouped selectbox options must be unique", "ValueError:", "Please Select a Valid Video Source"]:
        if token in combined:
            browser.close()
            fail(f"Browser displayed: {token}")
    if "MoneyPrinterTurbo" not in combined:
        browser.close(); fail("MoneyPrinterTurbo UI not found")
    if "Pexels" not in combined:
        browser.close(); fail("Pexels option not visible")
    if "Ollama Director Auto Media" not in combined and "Ollama Director" not in combined:
        browser.close(); fail("Ollama Director option not visible")
    page.screenshot(path=str(ROOT / "V7_PLAYWRIGHT_PASS.png"), full_page=True)
    browser.close()
ok("Playwright browser smoke test")

print()
print("============================================================")
print(" ALL V7 TESTS PASSED")
print("============================================================")
