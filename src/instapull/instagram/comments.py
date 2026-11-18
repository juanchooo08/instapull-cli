"""Publicacion de comentarios, con limites estrictos y sin repeticiones."""

from __future__ import annotations

from ..config import Config
from ..db import Database
from ..logging_setup import get_logger
from ..models import DmResult, SavedItem, utcnow_iso
from .auth import InstagramSession
from .ratelimit import ActionBlocked, RateLimited, clasificar_error, pausa

log = get_logger(__name__)


class LimiteComentarios(Exception):
    """Se alcanzo el tope de comentarios de esta corrida."""


class ContadorComentarios:
    """Lleva la cuenta de comentarios publicados y corta al llegar al tope."""

    def __init__(self, maximo: int) -> None:
        self.maximo = maximo
        self.publicados = 0

    @property
    def quedan(self) -> int:
        return max(0, self.maximo - self.publicados)

    def verificar(self) -> None:
        if self.quedan <= 0:
            raise LimiteComentarios(
                f"Tope de {self.maximo} comentarios alcanzado en esta corrida"
            )


def publicar_comentario(
    session: InstagramSession,
    db: Database,
    config: Config,
    item: SavedItem,
    palabra: str,
    contador: ContadorComentarios,
) -> DmResult:
    """Comenta `palabra` en el post. Nunca comenta dos veces el mismo post.

    Ante cualquier senal de accion bloqueada propaga `ActionBlocked` para que la
    corrida se detenga de inmediato.
    """
    resultado = DmResult(keyword=palabra)

    if db.already_commented(item.shortcode):
        log.info("ya_comentado", shortcode=item.shortcode)
        return db.get_comment_action(item.shortcode)

    contador.verificar()

    # Pausa larga ANTES de escribir: la accion de escritura es la sensible.
    pausa(config.comments.action_delay_seconds, motivo="antes de comentar")

    try:
        comentario = session.client.media_comment(item.media_id, palabra)
    except Exception as exc:  # noqa: BLE001
        propio = clasificar_error(exc)
        resultado.estado = "blocked" if isinstance(propio, ActionBlocked) else "error"
        resultado.error = str(exc)[:500]
        db.save_comment_action(item.shortcode, resultado)
        if isinstance(propio, (ActionBlocked, RateLimited)):
            log.error(
                "comentario_bloqueado",
                shortcode=item.shortcode,
                detalle="Se detiene la corrida para no arriesgar la cuenta",
            )
            raise propio from exc
        log.warning("comentario_fallido", shortcode=item.shortcode, error=str(exc)[:200])
        return resultado

    contador.publicados += 1
    resultado.estado = "commented"
    resultado.comment_id = str(getattr(comentario, "pk", "") or "")
    resultado.commented_at = utcnow_iso()
    db.save_comment_action(item.shortcode, resultado)
    log.info(
        "comentario_publicado",
        shortcode=item.shortcode,
        palabra=palabra,
        publicados=contador.publicados,
        tope=contador.maximo,
    )
    return resultado
