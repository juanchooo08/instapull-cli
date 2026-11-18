"""Extraccion de fotogramas de video con ffmpeg."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..config import MediaConfig
from ..logging_setup import get_logger

log = get_logger(__name__)


class FfmpegNoDisponible(RuntimeError):
    """ffmpeg no esta instalado o no esta en el PATH."""


def ffmpeg_disponible() -> bool:
    return shutil.which("ffmpeg") is not None


def exigir_ffmpeg() -> None:
    if not ffmpeg_disponible():
        raise FfmpegNoDisponible(
            "No encuentro ffmpeg en el PATH. Instalalo con:\n"
            "    winget install Gyan.FFmpeg\n"
            "y despues abri una terminal nueva."
        )


def duracion_video(video: Path) -> float | None:
    """Duracion en segundos segun ffprobe, o None si no se pudo leer."""
    if shutil.which("ffprobe") is None:
        return None
    try:
        salida = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(video),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        datos = json.loads(salida.stdout or "{}")
        return float(datos.get("format", {}).get("duration", 0)) or None
    except Exception as exc:  # noqa: BLE001
        log.debug("ffprobe_fallo", video=str(video), error=str(exc)[:200])
        return None


def _muestreo_uniforme(rutas: list[Path], maximo: int) -> list[Path]:
    """Se queda con `maximo` fotogramas repartidos a lo largo del video."""
    if len(rutas) <= maximo:
        return rutas
    paso = len(rutas) / maximo
    return [rutas[int(i * paso)] for i in range(maximo)]


def extraer_frames(video: Path, destino: Path, config: MediaConfig) -> list[Path]:
    """Un fotograma cada `frame_interval_seconds`, redimensionado y acotado."""
    exigir_ffmpeg()
    destino.mkdir(parents=True, exist_ok=True)

    existentes = sorted(destino.glob("frame_*.jpg"))
    if existentes:
        log.debug("frames_reutilizados", cantidad=len(existentes))
        return _muestreo_uniforme(existentes, config.max_frames_per_video)

    fps = f"1/{max(1, config.frame_interval_seconds)}"
    comando = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-vf",
        f"fps={fps},scale='min({config.frame_max_width},iw)':-2",
        "-q:v",
        "3",
        str(destino / "frame_%03d.jpg"),
    ]
    try:
        subprocess.run(comando, capture_output=True, text=True, timeout=600, check=True)
    except subprocess.CalledProcessError as exc:
        log.warning("ffmpeg_error", video=str(video), stderr=(exc.stderr or "")[:300])
        return []
    except subprocess.TimeoutExpired:
        log.warning("ffmpeg_timeout", video=str(video))
        return []

    rutas = sorted(destino.glob("frame_*.jpg"))
    seleccion = _muestreo_uniforme(rutas, config.max_frames_per_video)
    log.info(
        "frames_extraidos",
        video=video.name,
        extraidos=len(rutas),
        enviados=len(seleccion),
    )
    return seleccion


def extraer_audio(video: Path, destino: Path) -> Path | None:
    """Pista de audio en WAV 16 kHz mono, lista para whisper."""
    exigir_ffmpeg()
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    comando = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(destino),
    ]
    try:
        subprocess.run(comando, capture_output=True, text=True, timeout=600, check=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("audio_no_extraido", video=str(video), error=str(exc)[:200])
        return None
    return destino if destino.exists() and destino.stat().st_size > 0 else None
