"""Acciones de interaccion con un post: seguir, like y guardar.

Todas son acciones de escritura sobre la cuenta real, asi que valen las mismas
reglas que para comentar: solo se ejecutan cuando el post las exige de verdad,
nunca de forma preventiva, y cualquier senal de bloqueo detiene la corrida.

`seguir` y `like` son PUBLICAS (el autor las ve). `guardar` es privada.
Etiquetar a terceros no se implementa a proposito: meteria a otras personas en
un flujo automatizado sin su consentimiento.
"""

from __future__ import annotations

from typing import Callable

from ..logging_setup import get_logger
from .auth import InstagramSession
from .ratelimit import ActionBlocked, RateLimited, clasificar_error, con_reintentos

log = get_logger(__name__)

# Requisitos que el bot puede cumplir por su cuenta
EJECUTABLES = ("seguir", "like", "guardar")


def _intentar(accion: Callable[[], object], descripcion: str) -> bool:
    """Ejecuta una accion de escritura y traduce sus fallos.

    Returns:
        True si salio bien. False si fallo por algo que no compromete la cuenta.

    Raises:
        ActionBlocked / RateLimited / SessionExpired: hay que parar la corrida.
    """
    try:
        con_reintentos(accion, max_retries=2, descripcion=descripcion)
    except Exception as exc:  # noqa: BLE001
        propio = clasificar_error(exc)
        if propio is not None:
            if isinstance(propio, (ActionBlocked, RateLimited)):
                log.error("accion_bloqueada", accion=descripcion)
            raise propio from exc
        log.warning("accion_fallida", accion=descripcion, error=str(exc)[:200])
        return False
    return True


def seguir_autor(session: InstagramSession, user_id: str | int, autor: str) -> bool:
    """Sigue al autor del post. ACCION PUBLICA."""
    try:
        objetivo = int(user_id)
    except (TypeError, ValueError):
        log.warning("follow_sin_user_id", autor=autor)
        return False
    if not _intentar(lambda: session.client.user_follow(objetivo), f"seguir a {autor}"):
        return False
    log.info("autor_seguido", autor=autor)
    return True


def seguir_por_username(session: InstagramSession, autor: str) -> bool:
    """Sigue al autor resolviendo antes su id. ACCION PUBLICA.

    Se usa cuando el requisito viene del caption y todavia no hay hilo de DM
    del que sacar el user_id.
    """
    if not autor:
        return False
    try:
        user_id = con_reintentos(
            lambda: session.client.user_id_from_username(autor),
            max_retries=2,
            descripcion=f"resolver usuario {autor}",
        )
    except Exception as exc:  # noqa: BLE001
        propio = clasificar_error(exc)
        if propio is not None:
            raise propio from exc
        log.warning("usuario_no_resuelto", autor=autor, error=str(exc)[:200])
        return False
    return seguir_autor(session, user_id, autor)


def dar_like(session: InstagramSession, media_id: str, shortcode: str) -> bool:
    """Da like al post. ACCION PUBLICA."""
    if not media_id:
        return False
    if not _intentar(lambda: session.client.media_like(media_id), f"like a {shortcode}"):
        return False
    log.info("post_likeado", shortcode=shortcode)
    return True


def guardar_post(session: InstagramSession, media_id: str, shortcode: str) -> bool:
    """Guarda el post en la coleccion privada. No es visible para el autor."""
    if not media_id:
        return False
    if not _intentar(
        lambda: session.client.media_save(media_id), f"guardar {shortcode}"
    ):
        return False
    log.info("post_guardado", shortcode=shortcode)
    return True
