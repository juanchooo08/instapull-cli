"""Descarga de los medios a data/media/<shortcode>/."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from ..config import Config
from ..logging_setup import get_logger
from ..models import MediaType, SavedItem
from .ratelimit import con_reintentos

log = get_logger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _urls_de_media(media: Any) -> list[tuple[str, str]]:
    """Devuelve [(url, extension)] de un objeto Media de instagrapi."""
    salida: list[tuple[str, str]] = []
    tipo = getattr(media, "media_type", 0)

    if tipo == 8:  # carrusel
        for recurso in getattr(media, "resources", []) or []:
            if getattr(recurso, "media_type", 1) == 2 and getattr(recurso, "video_url", None):
                salida.append((str(recurso.video_url), ".mp4"))
            elif getattr(recurso, "thumbnail_url", None):
                salida.append((str(recurso.thumbnail_url), ".jpg"))
        return salida

    if tipo == 2 and getattr(media, "video_url", None):
        salida.append((str(media.video_url), ".mp4"))
        # La portada sirve como fotograma de respaldo si ffmpeg falla
        if getattr(media, "thumbnail_url", None):
            salida.append((str(media.thumbnail_url), ".jpg"))
        return salida

    if getattr(media, "thumbnail_url", None):
        salida.append((str(media.thumbnail_url), ".jpg"))
    return salida


def descargar_medio(item: SavedItem, media: Any, config: Config) -> SavedItem:
    """Descarga los archivos del elemento y actualiza `item` con sus rutas."""
    destino: Path = config.media_root / item.shortcode
    destino.mkdir(parents=True, exist_ok=True)
    item.media_dir = str(destino)

    if not config.media.download_media:
        log.info("descarga_desactivada", shortcode=item.shortcode)
        return item

    urls = _urls_de_media(media)
    if not urls:
        log.warning("sin_urls_de_medio", shortcode=item.shortcode)
        return item

    archivos: list[str] = []
    with httpx.Client(
        timeout=60, follow_redirects=True, headers={"User-Agent": _UA}
    ) as cliente:
        for indice, (url, extension) in enumerate(urls, start=1):
            ruta = destino / f"{indice:02d}{extension}"
            if ruta.exists() and ruta.stat().st_size > 0:
                archivos.append(str(ruta))
                continue

            def _bajar(u: str = url, r: Path = ruta) -> None:
                with cliente.stream("GET", u) as respuesta:
                    respuesta.raise_for_status()
                    with r.open("wb") as fh:
                        for bloque in respuesta.iter_bytes(64_000):
                            fh.write(bloque)

            try:
                con_reintentos(
                    _bajar,
                    max_retries=3,
                    base_delay=3.0,
                    descripcion=f"descargar {ruta.name}",
                )
                archivos.append(str(ruta))
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "descarga_fallida",
                    shortcode=item.shortcode,
                    archivo=ruta.name,
                    error=str(exc)[:200],
                )

    item.media_files = archivos
    log.info("medio_descargado", shortcode=item.shortcode, archivos=len(archivos))
    return item


def ruta_video(item: SavedItem) -> Path | None:
    """Primer archivo de video del elemento, si lo hay."""
    if item.media_type not in (MediaType.VIDEO, MediaType.CAROUSEL):
        return None
    for archivo in item.media_files:
        if archivo.lower().endswith(".mp4"):
            return Path(archivo)
    return None


def rutas_imagen(item: SavedItem) -> list[Path]:
    """Archivos de imagen del elemento."""
    return [
        Path(a)
        for a in item.media_files
        if a.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ]
