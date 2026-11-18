"""Control de ritmo: pausas con jitter, backoff exponencial y parada limpia.

Nada de reintentos agresivos: ante una senal de bloqueo se aborta la corrida
guardando el progreso, en vez de insistir.
"""

from __future__ import annotations

import random
import time
from typing import Callable, Sequence, TypeVar

from ..logging_setup import get_logger

log = get_logger(__name__)
T = TypeVar("T")


class InstaPullError(Exception):
    """Base de todos los errores propios."""


class SessionExpired(InstaPullError):
    """La sesion guardada ya no sirve; hay que volver a loguearse."""


class ActionBlocked(InstaPullError):
    """Instagram bloqueo la accion (feedback_required, challenge, etc.)."""


class RateLimited(InstaPullError):
    """Se alcanzo un limite de peticiones: hay que parar y guardar progreso."""


# Fragmentos que aparecen en los mensajes de instagrapi/instaloader ante bloqueos
_SENALES_BLOQUEO = (
    "feedback_required",
    "challenge_required",
    "checkpoint_required",
    "spam",
    "action blocked",
    "we restrict certain activity",
)
_SENALES_RATE = (
    "please wait a few minutes",
    "rate limit",
    "too many requests",
    "wait a few minutes before you try again",
)
_SENALES_SESION = (
    "login_required",
    "not logged in",
    "logged out",
    "user_has_logged_out",
)


def clasificar_error(exc: BaseException) -> InstaPullError | None:
    """Traduce una excepcion de la libreria a un error propio, si corresponde."""
    texto = f"{type(exc).__name__}: {exc}".lower()
    if any(s in texto for s in _SENALES_BLOQUEO):
        return ActionBlocked(str(exc))
    if any(s in texto for s in _SENALES_RATE):
        return RateLimited(str(exc))
    if any(s in texto for s in _SENALES_SESION):
        return SessionExpired(str(exc))
    return None


def pausa(rango: Sequence[float], motivo: str = "peticion") -> None:
    """Duerme un tiempo aleatorio dentro del rango (min, max) en segundos."""
    minimo, maximo = float(rango[0]), float(rango[1])
    if maximo < minimo:
        minimo, maximo = maximo, minimo
    segundos = random.uniform(minimo, maximo)
    log.debug("pausa", motivo=motivo, segundos=round(segundos, 1))
    time.sleep(segundos)


def con_reintentos(
    fn: Callable[[], T],
    max_retries: int = 4,
    base_delay: float = 5.0,
    descripcion: str = "operacion",
) -> T:
    """Ejecuta `fn` con backoff exponencial + jitter.

    Los errores de bloqueo, rate limit o sesion expirada NO se reintentan:
    se propagan de inmediato para que la corrida pare limpio.
    """
    ultimo: BaseException | None = None
    for intento in range(1, max_retries + 1):
        try:
            return fn()
        except (ActionBlocked, RateLimited, SessionExpired):
            raise
        except Exception as exc:  # noqa: BLE001 - se clasifica abajo
            propio = clasificar_error(exc)
            if propio is not None:
                raise propio from exc
            ultimo = exc
            if intento == max_retries:
                break
            espera = base_delay * (2 ** (intento - 1)) * random.uniform(0.8, 1.4)
            log.warning(
                "reintento",
                operacion=descripcion,
                intento=intento,
                de=max_retries,
                espera_s=round(espera, 1),
                error=str(exc)[:200],
            )
            time.sleep(espera)
    assert ultimo is not None
    raise ultimo
