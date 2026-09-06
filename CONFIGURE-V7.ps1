param(
  [Parameter(Mandatory=$true)][string]$RepoPath,
  [string]$Model = "qwen3:8b"
)
$ErrorActionPreference = "Stop"
$cfg = Join-Path $RepoPath "config.toml"
$example = Join-Path $RepoPath "config.example.toml"
if (-not (Test-Path $cfg)) { Copy-Item $example $cfg }
$t = Get-Content $cfg -Raw

function Set-Line([string]$name,[string]$value) {
  $pattern = "(?m)^" + [regex]::Escape($name) + "\s*=.*$"
  if ($script:t -match $pattern) {
    $script:t = [regex]::Replace($script:t, $pattern, "$name = $value", 1)
  } else {
    $script:t += "`n$name = $value`n"
  }
}

Set-Line "llm_provider" '"ollama"'
Set-Line "ollama_model_name" '"qwen3:8b"'
Set-Line "ollama_base_url" '"http://host.docker.internal:11434/v1"'
Set-Line "video_source" '"ollama_auto_media"'
Set-Line "match_materials_to_script" "true"
Set-Line "edge_tts_timeout" "150"
Set-Line "expressive_tts_enabled" "true"
Set-Line "expressive_tts_profile" '"sermon"'
Set-Line "chatterbox_base_url" '"http://chatterbox:4123"'
Set-Line "pexels_api_keys" '["somO1jtfSV0EQTc4sq9ELMTF700qSoqEZH8of8q5i6lpkN0Ms3MVxjrL"]'

Set-Content $cfg $t -Encoding UTF8
Write-Host "[OK] Ollama qwen3:8b configured"
Write-Host "[OK] Pexels fallback key configured locally"
