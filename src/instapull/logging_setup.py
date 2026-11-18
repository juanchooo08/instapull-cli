"""Logging estructurado: consola legible + archivo rotativo."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import structlog


class _Renderer:
    """Render unico y legible, compartido por consola y archivo."""

    def __init__(self) -> None:
        self._consola = structlog.dev.ConsoleRenderer(colors=True)

    def __call__(self, logger, name, event_dict):  # type: ignore[no-untyped-def]
        return self._consola(logger, name, event_dict)


def setup_logging(log_file: Path, verbose: bool = False) -> structlog.BoundLogger:
    """Configura structlog y devuelve el logger raiz de la aplicacion."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    nivel = logging.DEBUG if verbose else logging.INFO

    consola = logging.StreamHandler()
    consola.setFormatter(logging.Formatter("%(message)s"))

    archivo = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    archivo.setFormatter(logging.Formatter("%(message)s"))

    raiz = logging.getLogger()
    raiz.handlers.clear()
    raiz.setLevel(nivel)
    raiz.addHandler(consola)
    raiz.addHandler(archivo)

    # Librerias ruidosas
    for ruidosa in (
        "httpx",
        "httpcore",
        "urllib3",
        "instaloader",
        "public_api",
        "private_request",
    ):
        logging.getLogger(ruidosa).setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _Renderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(nivel),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    return structlog.get_logger("instapull")


def get_logger(nombre: str = "instapull") -> structlog.BoundLogger:
    return structlog.get_logger(nombre)
