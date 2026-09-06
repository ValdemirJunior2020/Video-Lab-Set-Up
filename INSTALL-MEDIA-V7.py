
from pathlib import Path
import shutil, sys
from datetime import datetime

ROOT = Path(sys.argv[1]).resolve()
SOURCE = Path(sys.argv[2]).resolve()
TARGET = ROOT / "app" / "services" / "auto_media.py"
if not TARGET.exists():
    raise SystemExit(f"[ERROR] Missing {TARGET}")
if not SOURCE.exists():
    raise SystemExit(f"[ERROR] Missing {SOURCE}")
backup = ROOT / ".ollama-studio-backups" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-v7-media") / "app" / "services" / "auto_media.py"
backup.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(TARGET, backup)
shutil.copy2(SOURCE, TARGET)
print("[OK] Resilient auto-media V7 installed")
print(f"[OK] Backup: {backup}")
