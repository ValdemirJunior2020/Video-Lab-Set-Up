import io
import re
import threading
from pathlib import Path

import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

app = FastAPI(title="MoneyPrinterTurbo Chatterbox Expressive TTS", version="8.0")
_model = None
_model_lock = threading.Lock()
_generate_lock = threading.Lock()

PROFILES = {
    "warm": {"exaggeration": 0.58, "cfg_weight": 0.42},
    "documentary": {"exaggeration": 0.62, "cfg_weight": 0.38},
    "inspirational": {"exaggeration": 0.72, "cfg_weight": 0.34},
    "emotional": {"exaggeration": 0.78, "cfg_weight": 0.31},
    "dramatic": {"exaggeration": 0.86, "cfg_weight": 0.28},
    "sermon": {"exaggeration": 0.80, "cfg_weight": 0.29},
    "calm": {"exaggeration": 0.48, "cfg_weight": 0.45},
}

class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    profile: str = "sermon"
    reference_audio: str | None = None


def _load_model():
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            from chatterbox.tts import ChatterboxTTS
            _model = ChatterboxTTS.from_pretrained(device="cpu")
    return _model


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


@app.get("/health")
def health():
    return {
        "ok": True,
        "engine": "chatterbox",
        "mode": "cpu",
        "model_loaded": _model is not None,
        "profiles": sorted(PROFILES),
    }


@app.post("/v1/tts")
def synthesize(req: TTSRequest):
    text = _clean(req.text)
    if not text:
        raise HTTPException(status_code=400, detail="empty text")
    profile = PROFILES.get(req.profile, PROFILES["sermon"])
    reference = (req.reference_audio or "").strip() or None
    if reference and not Path(reference).exists():
        reference = None
    try:
        model = _load_model()
        kwargs = {
            "exaggeration": profile["exaggeration"],
            "cfg_weight": profile["cfg_weight"],
        }
        if reference:
            kwargs["audio_prompt_path"] = reference
        with _generate_lock:
            wav = model.generate(text, **kwargs)
        arr = wav.detach().cpu().numpy() if hasattr(wav, "detach") else wav
        while getattr(arr, "ndim", 1) > 1:
            arr = arr[0]
        buf = io.BytesIO()
        sf.write(buf, arr, model.sr, format="WAV", subtype="PCM_16")
        payload = buf.getvalue()
        if len(payload) < 2048:
            raise RuntimeError("generated audio too small")
        return Response(content=payload, media_type="audio/wav")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chatterbox generation failed: {exc}")
