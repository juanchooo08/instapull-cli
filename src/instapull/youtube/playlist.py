"""Listado y descarga de videos de una playlist de YouTube, via yt-dlp.

El id del elemento es "yt:<video_id>" para no chocar nunca con un shortcode de
Instagram en la tabla `items`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import Config
from ..logging_setup import get_logger
from ..models import MediaType, SavedItem

log = get_logger(__name__)

PREFIJO = "yt:"


class YtDlpNoDisponible(RuntimeError):
    """yt-dlp no esta instalado o no esta en el PATH."""


def binario_yt_dlp() -> str:
    # El del entorno virtual primero: el del sistema suele estar mas viejo
    propio = Path(sys.executable).with_name("yt-dlp")
    if propio.exists():
        return str(propio)
    ruta = shutil.which("yt-dlp")
    if not ruta:
        raise YtDlpNoDisponible(
            "Falta yt-dlp. Instalalo con:  pip install yt-dlp   (o: brew install yt-dlp)"
        )
    return ruta


def _correr(args: list[str], timeout: int) -> str:
    proceso = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False
    )
    if proceso.returncode != 0:
        raise RuntimeError(
            f"yt-dlp fallo ({proceso.returncode}): {(proceso.stderr or '')[-500:]}"
        )
    return proceso.stdout


def video_id(shortcode: str) -> str:
    """'yt:abc123' -> 'abc123'."""
    return shortcode[len(PREFIJO) :] if shortcode.startswith(PREFIJO) else shortcode


def listar_playlist(url: str, limite: int) -> list[SavedItem]:
    """Elementos de la playlist, del mas nuevo al mas viejo segun el orden de la lista.

    Usa `--flat-playlist`: una sola peticion, sin bajar nada. La descripcion no
    viene en este modo; se completa al descargar cada video.
    """
    salida = _correr(
        [
            binario_yt_dlp(),
            "--no-update",
            "--flat-playlist",
            "--dump-json",
            "--ignore-errors",
            "--playlist-end",
            str(max(limite, 1)),
            url,
        ],
        timeout=180,
    )

    items: list[SavedItem] = []
    for linea in salida.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            datos = json.loads(linea)
        except json.JSONDecodeError:
            continue
        vid = datos.get("id") or ""
        if not vid:
            continue
        duracion = datos.get("duration")
        items.append(
            SavedItem(
                shortcode=f"{PREFIJO}{vid}",
                media_id=vid,
                author=datos.get("uploader") or datos.get("channel") or "",
                caption=datos.get("title") or "",
                permalink=datos.get("url") or f"https://www.youtube.com/watch?v={vid}",
                media_type=MediaType.VIDEO,
                video_duration=float(duracion) if duracion else None,
            )
        )
    log.info("playlist_listada", url=url, elementos=len(items))
    return items


def _texto_de_vtt(ruta: Path) -> str:
    """VTT -> texto plano, sin marcas de tiempo ni lineas repetidas."""
    lineas: list[str] = []
    for cruda in ruta.read_text(encoding="utf-8", errors="ignore").splitlines():
        linea = cruda.strip()
        if (
            not linea
            or "-->" in linea
            or linea.startswith(("WEBVTT", "Kind:", "Language:", "NOTE"))
            or linea.isdigit()
        ):
            continue
        # Los subtitulos automaticos traen etiquetas <c> y tiempos por palabra
        linea = re.sub(r"<[^>]+>", "", linea).strip()
        if linea and (not lineas or lineas[-1] != linea):
            lineas.append(linea)
    return " ".join(lineas)


def descargar_video(item: SavedItem, config: Config) -> tuple[SavedItem, str]:
    """Baja el video (y sus subtitulos) a data/media/yt_<id>/.

    Devuelve el item actualizado y el transcript tomado de los subtitulos
    (cadena vacia si el video no tiene; en ese caso el pipeline usa whisper).
    """
    yt = config.youtube
    vid = video_id(item.shortcode)
    destino = config.media_root / f"yt_{vid}"
    destino.mkdir(parents=True, exist_ok=True)
    item.media_dir = str(destino)

    args = [
        binario_yt_dlp(),
        "--no-update",
        "--no-playlist",
        "--no-progress",
        "--write-info-json",
        "--write-thumbnail",
        "--convert-thumbnails",
        "jpg",
        "-f",
        f"bv*[height<={yt.max_height}]+ba/b[height<={yt.max_height}]/b",
        "--merge-output-format",
        "mp4",
        "-o",
        str(destino / "video.%(ext)s"),
    ]
    if not config.media.download_media:
        # Solo metadatos y subtitulos: sin video no hay fotogramas
        args.append("--skip-download")
    args.append(item.permalink)

    _correr(args, timeout=yt.download_timeout_seconds)

    if yt.prefer_subs:
        _bajar_subtitulos(item, destino, yt.sub_langs)

    # Metadatos completos (incluida la descripcion, donde viven los enlaces)
    info = destino / "video.info.json"
    if info.exists():
        datos = json.loads(info.read_text(encoding="utf-8", errors="ignore"))
        titulo = datos.get("title") or item.caption
        descripcion = datos.get("description") or ""
        item.caption = f"{titulo}\n\n{descripcion}".strip()
        item.author = datos.get("uploader") or datos.get("channel") or item.author
        item.taken_at = _fecha(datos.get("upload_date", ""))
        if datos.get("duration"):
            item.video_duration = float(datos["duration"])

    archivos = [
        str(p)
        for p in sorted(destino.iterdir())
        if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".jpg", ".png", ".webp")
    ]
    item.media_files = archivos

    transcript = ""
    for idioma in yt.sub_langs:
        vtt = destino / f"video.{idioma}.vtt"
        if vtt.exists():
            transcript = _texto_de_vtt(vtt)
            if transcript:
                log.info("subtitulos_usados", shortcode=item.shortcode, idioma=idioma)
                break

    log.info(
        "video_descargado",
        shortcode=item.shortcode,
        archivos=len(archivos),
        con_subtitulos=bool(transcript),
    )
    return item, transcript


def _bajar_subtitulos(item: SavedItem, destino: Path, idiomas: list[str]) -> None:
    """Llamada aparte y no critica: YouTube devuelve 429 en los subtitulos muy
    seguido, y el video ya esta bajado. Sin subtitulos se transcribe con whisper.
    """
    try:
        _correr(
            [
                binario_yt_dlp(),
                "--no-update",
                "--no-playlist",
                "--no-progress",
                "--skip-download",
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs",
                ",".join(idiomas),
                "--sub-format",
                "vtt",
                "-o",
                str(destino / "video.%(ext)s"),
                item.permalink,
            ],
            timeout=180,
        )
    except Exception as exc:  # noqa: BLE001 - nunca debe tumbar la corrida
        log.warning(
            "sin_subtitulos",
            shortcode=item.shortcode,
            detalle=str(exc)[-200:],
        )


def _fecha(aaaammdd: str) -> str:
    """'20261118' -> '2026-11-18'."""
    if len(aaaammdd) == 8 and aaaammdd.isdigit():
        return f"{aaaammdd[:4]}-{aaaammdd[4:6]}-{aaaammdd[6:]}"
    return ""
