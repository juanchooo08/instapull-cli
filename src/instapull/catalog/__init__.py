"""Catalogo global de herramientas: deduplicacion y vista interactiva."""

from .html import render_catalogo
from .inventario import escanear
from .normalize import canonicalizar, es_ruido

__all__ = ["canonicalizar", "es_ruido", "escanear", "render_catalogo"]
