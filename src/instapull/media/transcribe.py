"""Transcripcion de audio con faster-whisper, local y en CPU."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import MediaConfig
from ..logging_setup import get_logger

log = get_logger(__name__)

# El modelo pesa cientos de MB: se carga una sola vez por proceso.
_modelo: Any = None
_modelo_clave: tuple[str, str, str] | None = None


def _cargar_modelo(config: MediaConfig) -> Any:
    global _modelo, _modelo_clave
    clave = (config.whisper_model, config.whisper_device, config.whisper_compute_type)
    if _modelo is not None and _modelo_clave == clave:
        return _modelo

    from faster_whisper import WhisperModel

    log.info(
        "cargando_whisper", modelo=config.whisper_model, device=config.whisper_device
    )
    _modelo = WhisperModel(
        config.whisper_model,
        device=config.whisper_device,
        compute_type=config.whisper_compute_type,
    )
    _modelo_clave = clave
    return _modelo


def transcribir(audio: Path, config: MediaConfig) -> str:
    """Devuelve la transcripcion del audio, o cadena vacia si falla."""
    if not audio.exists():
        return ""
    try:
        modelo = _cargar_modelo(config)
        segmentos, info = modelo.transcribe(str(audio), beam_size=1, vad_filter=True)
        texto = " ".join(s.text.strip() for s in segmentos).strip()
        log.info(
            "transcripcion_lista",
            archivo=audio.name,
            idioma=getattr(info, "language", "?"),
            caracteres=len(texto),
        )
        return texto
    except Exception as exc:  # noqa: BLE001
        log.warning("transcripcion_fallida", archivo=str(audio), error=str(exc)[:300])
        return ""
