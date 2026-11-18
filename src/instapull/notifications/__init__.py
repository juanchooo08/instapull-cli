"""Notificaciones: resumen diario por correo."""

from .email import DigestResult, EmailNotifier, debe_enviar_ahora

__all__ = ["DigestResult", "EmailNotifier", "debe_enviar_ahora"]
