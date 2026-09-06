from pathlib import Path
from datetime import datetime
import shutil
import sys
import re
import ast

bundle = Path(__file__).resolve().parent
if len(sys.argv) > 1 and sys.argv[1].strip():
    root = Path(sys.argv[1].strip().strip('"')).resolve()
else:
    root = Path(r"C:\Users\nobody\Downloads\Video-Projetos\MoneyPrinterTurbo").resolve()

required = [
    root / "app" / "services" / "auto_media.py",
    root / "docker-compose.yml",
    root / "config.toml",
]
missing = [str(p) for p in required if not p.exists()]
if missing:
    print("[FAIL] MoneyPrinterTurbo project was not found:")
    for item in missing:
        print("  ", item)
    raise SystemExit(1)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S-pydantic-scene-agent")
backup = root / ".ollama-studio-backups" / stamp

def backup_file(path: Path):
    rel = path.relative_to(root)
    dest = backup / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)

def replace_file(src: Path, dest: Path):
    if dest.exists():
        backup_file(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print("[PATCHED]", dest.relative_to(root))

replace_file(bundle / "auto_media.py", root / "app" / "services" / "auto_media.py")
replace_file(bundle / "scene_planner_agent.py", root / "app" / "services" / "scene_planner_agent.py")
replace_file(bundle / "docker-compose.yml", root / "docker-compose.yml")
replace_file(bundle / "config.example.toml", root / "config.example.toml")

service_dest = root / "scene_planner_service"
if service_dest.exists():
    for file in service_dest.rglob("*"):
        if file.is_file():
            backup_file(file)
service_dest.mkdir(parents=True, exist_ok=True)
shutil.copy2(bundle / "scene_planner_service" / "Dockerfile", service_dest / "Dockerfile")
shutil.copy2(bundle / "scene_planner_service" / "service.py", service_dest / "service.py")
print("[PATCHED] scene_planner_service")

# Patch config.toml in place without printing or changing any API key.
config_path = root / "config.toml"
backup_file(config_path)
text = config_path.read_text(encoding="utf-8-sig")
settings = {
    "pydantic_scene_planner_enabled": "true",
    "pydantic_scene_planner_url": '"http://scene-planner:4130"',
    "pydantic_scene_planner_timeout_seconds": "300",
    "pydantic_scene_planner_retries": "3",
}

app_pos = text.find("[app]")
if app_pos < 0:
    raise SystemExit("[FAIL] config.toml has no [app] section")

next_section = text.find("\n[", app_pos + len("[app]"))
if next_section < 0:
    next_section = len(text)

app_block = text[app_pos:next_section]
for key, value in settings.items():
    pattern = re.compile(rf"(?m)^\s*{re.escape(key)}\s*=.*$")
    line = f"{key} = {value}"
    if pattern.search(app_block):
        app_block = pattern.sub(line, app_block, count=1)
    else:
        app_block += "\n" + line

text = text[:app_pos] + app_block + text[next_section:]
config_path.write_text(text, encoding="utf-8")
print("[PATCHED] config.toml scene-planner settings (API keys were not printed)")

# Syntax gate.
for rel in [
    Path("app/services/auto_media.py"),
    Path("app/services/scene_planner_agent.py"),
    Path("scene_planner_service/service.py"),
]:
    ast.parse((root / rel).read_text(encoding="utf-8"), filename=str(rel))
    print("[PASS] syntax", rel)

print("[PASS] .git untouched")
print("[PASS] .env untouched")
print("[PASS] Backup:", backup)
