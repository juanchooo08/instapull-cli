"""Deteccion de la consigna "comenta X" en el texto de una publicacion.

Primero regex por capas (barato y determinista); si nada dispara con confianza,
se le pregunta al modelo.
"""

from __future__ import annotations

import re
from typing import Any

from ..logging_setup import get_logger
from ..models import KeywordDetection
from .prompts import mensaje_keyword

log = get_logger(__name__)

# Palabras que aparecen tras el verbo pero NO son una consigna de bot
_NO_SON_CONSIGNA = {
    "que",
    "qué",
    "lo",
    "tu",
    "tus",
    "si",
    "abajo",
    "aqui",
    "aquí",
    "esto",
    "algo",
    "below",
    "what",
    "your",
    "this",
    "here",
    "y",
    "en",
    "el",
    "la",
    "me",
    "te",
    "un",
    "una",
    "mas",
    "más",
    "cual",
    "cuál",
    "como",
    "cómo",
}

_VERBOS = (
    r"(?:comenta|comentá|comentar|comente|comment|escribe|escribí|escribi|escribir|"
    r"manda|mandá|envia|envía|enviá|deja|dejá|pon|poné|pone|type|write|drop|send)"
)

# Capa 1: verbo + palabra entre comillas -> la mas confiable
_RE_COMILLAS = re.compile(
    rf"{_VERBOS}\b[^\"'“”«]{{0,30}}[\"'“«]([\w\-\.#]{{2,25}})[\"'”»]",
    re.IGNORECASE | re.UNICODE,
)

# Capa 2: verbo + PALABRA EN MAYUSCULAS
_RE_MAYUSCULAS = re.compile(
    rf"{_VERBOS}\b[^\wÁÉÍÓÚÑ]{{0,25}}([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9\-]{{1,24}})\b",
    re.UNICODE,
)

# Capa 3: verbo + palabra suelta (menos confiable, exige promesa de DM)
_RE_SUELTA = re.compile(
    rf"{_VERBOS}\s+(?:la\s+palabra\s+|el\s+codigo\s+|the\s+word\s+)?([\w\-]{{2,25}})\b",
    re.IGNORECASE | re.UNICODE,
)

# Senal de que el post promete mandar algo por privado
_RE_PROMESA = re.compile(
    r"(te\s+(?:lo\s+)?(?:env[ií]o|mando|paso)|te\s+llega|por\s+(?:dm|mensaje|privado)|"
    r"i'?ll\s+send|in\s+your\s+dms?|link\s+en\s+el\s+dm|revisa\s+tus\s+mensajes)",
    re.IGNORECASE | re.UNICODE,
)


def _valida(palabra: str | None) -> bool:
    if not palabra:
        return False
    limpia = palabra.strip().strip("\"'“”«»").strip()
    if len(limpia) < 2 or len(limpia) > 25:
        return False
    return limpia.lower() not in _NO_SON_CONSIGNA


def detectar_por_regex(caption: str) -> KeywordDetection:
    """Aplica las tres capas de regex, de mas a menos confiable."""
    if not caption:
        return KeywordDetection()

    promesa = bool(_RE_PROMESA.search(caption))

    m = _RE_COMILLAS.search(caption)
    if m and _valida(m.group(1)):
        return KeywordDetection(
            pide_comentario=True, palabra=m.group(1), fuente="regex", confianza=0.95
        )

    m = _RE_MAYUSCULAS.search(caption)
    if m and _valida(m.group(1)):
        return KeywordDetection(
            pide_comentario=True,
            palabra=m.group(1),
            fuente="regex",
            confianza=0.9 if promesa else 0.8,
        )

    m = _RE_SUELTA.search(caption)
    if m and _valida(m.group(1)) and promesa:
        return KeywordDetection(
            pide_comentario=True, palabra=m.group(1), fuente="regex", confianza=0.7
        )

    return KeywordDetection(confianza=0.0)


def detectar_keyword(caption: str, cliente: Any | None = None) -> KeywordDetection:
    """Deteccion completa: regex y, si no alcanza, el modelo de IA."""
    porregex = detectar_por_regex(caption)
    if porregex.pide_comentario and porregex.confianza >= 0.8:
        return porregex

    if cliente is None:
        return porregex

    # Al modelo solo se lo molesta si el texto huele a consigna
    pistas = re.search(
        rf"{_VERBOS}|\bdm\b|mensaje directo|link en", caption or "", re.IGNORECASE
    )
    if not pistas:
        return porregex

    try:
        datos = cliente.chat_json(mensaje_keyword(caption))
        deteccion = KeywordDetection(
            pide_comentario=bool(datos.get("pide_comentario")),
            palabra=datos.get("palabra"),
            fuente="ia",
            confianza=float(datos.get("confianza") or 0.6),
        )
        if deteccion.pide_comentario and not _valida(deteccion.palabra):
            deteccion.pide_comentario = False
            deteccion.palabra = None
        log.info(
            "keyword_por_ia", pide=deteccion.pide_comentario, palabra=deteccion.palabra
        )
        return deteccion
    except Exception as exc:  # noqa: BLE001
        log.warning("keyword_ia_fallo", error=str(exc)[:200])
        return porregex
