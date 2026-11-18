"""Analisis de un elemento: arma el contexto y valida la salida del modelo."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..logging_setup import get_logger
from ..models import Analysis, MediaContext, ProcessedItem, ResolvedLink
from .client import AIClient, imagen_a_data_url
from .prompts import mensaje_analisis, mensaje_respuesta_dm

log = get_logger(__name__)


def _bloque_enlaces(links: list[ResolvedLink]) -> str:
    partes: list[str] = []
    for link in links:
        cabecera = f"- {link.url_final or link.url_original} ({link.tipo})"
        if link.titulo:
            cabecera += f" | {link.titulo}"
        partes.append(cabecera)
        if link.extracto:
            partes.append(link.extracto[:1500])
    return "\n".join(partes)


def _frames_a_data_urls(rutas: list[str] | list[Path]) -> list[str]:
    salida: list[str] = []
    for ruta in rutas:
        p = Path(ruta)
        if not p.exists():
            continue
        try:
            salida.append(imagen_a_data_url(p))
        except Exception as exc:  # noqa: BLE001
            log.warning("frame_ilegible", archivo=str(p), error=str(exc)[:150])
    return salida


def analizar_elemento(cliente: AIClient, procesado: ProcessedItem) -> Analysis:
    """Envia caption + imagenes + transcripcion + OCR + DM + enlaces en una sola llamada."""
    item = procesado.item
    media: MediaContext = procesado.media

    mensajes = mensaje_analisis(
        caption=item.caption,
        frames_data_urls=_frames_a_data_urls(media.frames),
        transcript=media.transcript,
        ocr=media.ocr_text,
        dm_texto=procesado.dm.dm_text,
        enlaces=_bloque_enlaces(procesado.links),
        autor=item.author,
        permalink=item.permalink,
    )

    datos: dict[str, Any] = cliente.chat_json(mensajes)
    analisis = Analysis.model_validate(datos)
    analisis.modelo = cliente.ultimo_modelo
    analisis.tokens = cliente.ultimos_tokens

    # Los enlaces ya resueltos siempre forman parte del resultado
    conocidos = {link.url_final or link.url_original for link in procesado.links}
    for url in sorted(conocidos):
        if url and url not in analisis.enlaces:
            analisis.enlaces.append(url)

    log.info(
        "elemento_analizado",
        shortcode=item.shortcode,
        categoria=analisis.categoria.value,
        valoracion=analisis.valoracion,
        modelo=analisis.modelo,
        tokens=analisis.tokens,
    )
    return analisis


def responder_dm_con_ia(cliente: AIClient, texto_bot: str) -> str | None:
    """Decide que contestarle al bot para avanzar hasta el enlace."""
    try:
        datos = cliente.chat_json(mensaje_respuesta_dm(texto_bot))
    except Exception as exc:  # noqa: BLE001
        log.warning("respuesta_dm_ia_fallo", error=str(exc)[:200])
        return None
    if not datos.get("responder"):
        return None
    texto = str(datos.get("texto") or "").strip()
    return texto[:100] or None
