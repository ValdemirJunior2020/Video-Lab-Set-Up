MoneyPrinterTurbo — PydanticAI Scene Planner V9

WHAT THIS FIXES
Your log showed:
  Ollama scene planner fallback:
  Invalid control character at: line 49 column 213

The old planner asked qwen3:8b for free-form JSON and then called json.loads().
One bad raw newline/control character could break the whole JSON response.

V9 changes the first scene-planning path to:

  MoneyPrinterTurbo
      -> PydanticAI Scene Planner
      -> Ollama qwen3:8b
      -> Ollama Native JSON Schema
      -> Pydantic validation
      -> validated scene objects only
      -> Pexels / Wikimedia / Internet Archive

If the new helper ever fails, your existing legacy Ollama planner still runs.
If that also fails, the deterministic sentence planner still runs.

NOT CHANGED
- Your .git is not touched.
- Your .env is not touched.
- Your Pexels key is not printed or replaced.
- Ollama remains qwen3:8b.
- Pexels remains available.
- Chatterbox expressive narration remains installed.
- Piper / Edge fallback behavior remains unchanged.

HOW TO INSTALL
Double-click:
  INSTALL-AND-TEST-V9.bat

It defaults to:
  C:\Users\nobody\Downloads\Video-Projetos\MoneyPrinterTurbo

If your project moves later, run:
  INSTALL-AND-TEST-V9.bat "D:\your\new\MoneyPrinterTurbo"

THE APPROVAL GATE
The installer will not print APPROVED until it verifies:
1. Python syntax
2. Docker Compose
3. PydanticAI service
4. REAL qwen3:8b native structured-output scene plan
5. Pydantic scene validation
6. MoneyPrinterTurbo -> agent connection
7. Pexels API
8. Existing Chatterbox service
9. WebUI
10. Microsoft Playwright Chromium browser test

After a successful test:
  V9_PLAYWRIGHT_PASS.png
will be created in the MoneyPrinterTurbo project root.

BACKUPS
Changed files are backed up under:
  .ollama-studio-backups\<timestamp>-pydantic-scene-agent


V9.1 SAFE-MEDIA HOTFIX

This also fixes the two media problems from the 04:13 log:

A) Pexels 400 Bad Request
   Raw narration/dialogue is no longer sent directly to Pexels.
   Queries are normalized, control characters removed, punctuation reduced,
   whitespace collapsed, and length capped before the API call.

B) FATAL "path is outside the allowed directory"
   The security rule in video.py is NOT disabled.
   Downloaded/generated scene clips are now written under:

     storage/local_videos/ollama_auto_media/<task-id>/

   That directory is already trusted by MoneyPrinterTurbo's video preprocessor.
   Task metadata still stays under:

     storage/tasks/<task-id>/ollama_auto_media/

This preserves the security boundary instead of weakening it.
