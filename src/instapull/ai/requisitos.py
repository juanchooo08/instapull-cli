"""Que exige cada post y cual es la via mas barata para conseguir el recurso.

No todos los posts funcionan igual: unos ponen el enlace en el propio caption,
otros piden comentar una palabra, otros ademas exigen que sigas la cuenta, y
algunos piden like o guardar. Interactuar cuesta acciones publicas y minutos de
espera, asi que primero se mira si el recurso ya esta a la vista.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from ..logging_setup import get_logger
from ..models import PostRequisitos
from .keyword import detectar_keyword

log = get_logger(__name__)

# Dominios que no son "el recurso": son el propio Instagram o enlaces de perfil
# que no llevan a ninguna parte util sin interactuar.
_DOMINIOS_VACIOS = (
    "instagram.com",
    "instagr.am",
    "ig.me",
    "facebook.com",
    "fb.me",
)

_PIDE_SEGUIR = re.compile(
    r"(s[ií]gue(?:me|nos)|seguime|que\s+me\s+sigas|debes\s+seguir|"
    r"ten[ée]s\s+que\s+seguir|tienes\s+que\s+seguir|solo\s+para\s+seguidores|"
    r"follow\s+me|follow\s+us|make\s+sure\s+(?:you'?re\s+)?follow|"
    r"must\s+be\s+following|be\s+following\s+me)",
    re.IGNORECASE | re.UNICODE,
)

_PIDE_LIKE = re.compile(
    r"(dale?\s+like|dej[aá]\s+(?:un\s+)?like|pon[eé]?\s+like|me\s+gusta\s+al\s+post|"
    r"like\s+(?:this|the)\s+(?:post|reel|video)|double\s+tap)",
    re.IGNORECASE | re.UNICODE,
)

_PIDE_GUARDAR = re.compile(
    r"(guard[aá]\s+(?:este|el)\s+(?:post|reel|video)|guardalo|gu[aá]rdalo|"
    r"save\s+(?:this|it|the\s+post))",
    re.IGNORECASE | re.UNICODE,
)

_PIDE_ETIQUETAR = re.compile(
    r"(etiquet[aá]\s+a|menciona\s+a|tag\s+a\s+friend|tag\s+someone)",
    re.IGNORECASE | re.UNICODE,
)

_ES_ENLACE_UTIL = re.compile(r"^https?://", re.IGNORECASE)


def _urls_utiles(urls: list[str]) -> list[str]:
    """Enlaces del caption que llevan a algo distinto de Instagram."""
    salida: list[str] = []
    for url in urls:
        if not _ES_ENLACE_UTIL.match(url):
            continue
        minuscula = url.lower()
        if any(dom in minuscula for dom in _DOMINIOS_VACIOS):
            continue
        if url not in salida:
            salida.append(url)
    return salida


def detectar_requisitos(
    caption: str,
    extraer_urls: Callable[[str], list[str]],
    cliente: Any | None = None,
) -> PostRequisitos:
    """Analiza el caption y decide via y requisitos.

    La via 'directa' gana siempre que el post ya muestre un enlace util: no
    tiene sentido comentar, seguir ni esperar un DM por algo que ya esta ahi.

    Args:
        caption: texto del post.
        extraer_urls: extractor de URLs (se inyecta para no acoplar con links/).
        cliente: cliente de IA opcional, para la deteccion fina de la consigna.
    """
    texto = caption or ""
    directas = _urls_utiles(extraer_urls(texto))

    exigencias: list[str] = []
    if _PIDE_SEGUIR.search(texto):
        exigencias.append("seguir")
    if _PIDE_LIKE.search(texto):
        exigencias.append("like")
    if _PIDE_GUARDAR.search(texto):
        exigencias.append("guardar")
    if _PIDE_ETIQUETAR.search(texto):
        exigencias.append("etiquetar")

    if directas:
        # Via directa: las exigencias se anotan para el informe, pero no hay
        # que cumplir ninguna para conseguir el recurso.
        log.info("via_directa", enlaces=len(directas))
        return PostRequisitos(
            via="directa", requisitos=[], urls_directas=directas, palabra=None
        )

    deteccion = detectar_keyword(texto, cliente)
    if deteccion.pide_comentario and deteccion.palabra:
        return PostRequisitos(
            via="comentario",
            requisitos=["comentar"] + exigencias,
            palabra=deteccion.palabra,
        )

    # Sin enlace y sin consigna: no queda mas que analizar el medio
    return PostRequisitos(via="ninguna", requisitos=exigencias, palabra=None)
