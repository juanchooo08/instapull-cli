"""Envio diario por correo del resumen de elementos nuevos (Resend).

Este modulo solo arma y manda el correo: no toca la base de datos. Quien lo
llama (el comando `instapull digest`) es el que decide que elementos entran y
el que registra el envio con `Database.registrar_digest`, de modo que un fallo
de red nunca marque como notificado algo que no salio.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from ..catalog import render_catalogo
from ..config import EmailConfig
from ..logging_setup import get_logger
from ..models import ProcessedItem
from .render import asunto_digest, render_html, render_texto

log = get_logger(__name__)

RESEND_URL = "https://api.resend.com/emails"


class DigestResult(BaseModel):
    """Que paso con el intento de envio."""

    # sent | dry_run | disabled | sin_novedades | error
    estado: str
    asunto: str = ""
    message_id: str = ""
    shortcodes: list[str] = Field(default_factory=list)
    detalle: str = ""
    error: str | None = None

    @property
    def enviado(self) -> bool:
        return self.estado == "sent"


def debe_enviar_ahora(
    config: EmailConfig, ultimo_envio: str | None, ahora: datetime | None = None
) -> tuple[bool, str]:
    """Decide si toca mandar el digest de hoy.

    Pensado para correr desde el Programador de tareas cada pocas horas: manda
    una sola vez por dia, y recien pasada la hora configurada.

    Args:
        config: bloque `email:` de la configuracion.
        ultimo_envio: `sent_at` (ISO-8601 UTC) del ultimo digest enviado, o None.
        ahora: hora local; por defecto la del sistema. Explicito para los tests.

    Returns:
        (si_toca, motivo_legible)
    """
    momento = ahora or datetime.now().astimezone()
    if momento.hour < config.send_hour:
        return False, (
            f"todavia no son las {config.send_hour}:00 (son las {momento.hour}:00)"
        )

    if ultimo_envio:
        try:
            previo = datetime.fromisoformat(ultimo_envio).astimezone(momento.tzinfo)
        except ValueError:
            return True, "el ultimo envio tiene una fecha ilegible; se manda igual"
        if previo.date() == momento.date():
            return False, f"ya se envio hoy ({previo.strftime('%H:%M')})"

    return True, "toca enviar"


class EmailNotifier:
    """Envia por correo el resumen diario de los elementos nuevos."""

    def __init__(
        self, config: EmailConfig, api_key: str = "", timeout: int = 30
    ) -> None:
        self.config = config
        self.api_key = api_key
        self.timeout = timeout

    # --- validacion ----------------------------------------------------

    def problema_de_configuracion(self) -> str | None:
        """Primer motivo por el que no se podria enviar, o None si esta todo."""
        if self.config.provider != "resend":
            return (
                f"proveedor '{self.config.provider}' no soportado; "
                "el unico implementado es 'resend'"
            )
        if not self.api_key:
            return "falta RESEND_API_KEY en el entorno"
        if not self.config.from_address:
            return "falta email.from_address en config.yaml"
        if not self.config.to_address:
            return "falta email.to_address en config.yaml"
        return None

    # --- adjuntos ------------------------------------------------------

    def _adjunto_catalogo(
        self, catalogo: list[dict[str, Any]] | None, dia: str
    ) -> dict[str, str] | None:
        """Catalogo interactivo listo para Resend, o None si no corresponde.

        Resend acepta hasta ~40 MB por correo; el catalogo es texto plano y
        pesa unos pocos KB por herramienta, pero se corta igual por las dudas
        antes que arriesgar que el correo entero rebote.
        """
        if not catalogo or not self.config.attach_catalog:
            return None

        html = render_catalogo(
            catalogo, dia, dias_nuevo=self.config.catalog_new_days
        )
        crudo = html.encode("utf-8")
        if len(crudo) > 8_000_000:
            log.warning("catalogo_muy_grande", bytes=len(crudo))
            return None

        return {
            "filename": f"catalogo-{dia}.html",
            "content": base64.b64encode(crudo).decode("ascii"),
        }

    # --- envio ---------------------------------------------------------

    def send_daily_digest(
        self,
        items: list[ProcessedItem],
        fecha: str | None = None,
        dry_run: bool = False,
        catalogo: list[dict[str, Any]] | None = None,
        solo_catalogo: bool = False,
    ) -> DigestResult:
        """Envia el resumen de los elementos nuevos.

        Args:
            items: elementos nuevos desde el ultimo envio, ya analizados.
            fecha: dia del resumen (YYYY-MM-DD); por defecto, hoy en hora local.
            dry_run: arma el correo y lo valida, pero no lo manda.
            catalogo: filas de `Database.catalogo()`. Si viene y
                `email.attach_catalog` esta activo, el correo lleva adjunto el
                catalogo interactivo completo (no solo lo de hoy).
            solo_catalogo: manda el correo aunque no haya elementos nuevos, con
                el catalogo como unico contenido util. Sirve para reenviarlo a
                mano sin esperar a que aparezcan posts nuevos.

        Returns:
            El resultado del intento. Nunca lanza por un fallo de red o de la
            API: el error viaja en `DigestResult.error` para que el que llama lo
            registre y no marque los elementos como notificados.
        """
        if not self.config.enabled:
            return DigestResult(
                estado="disabled",
                detalle="el envio por correo esta apagado (email.enabled: false)",
            )

        analizados = [p for p in items if p.analysis is not None]
        if not analizados and not solo_catalogo:
            return DigestResult(
                estado="sin_novedades", detalle="no hay elementos nuevos que notificar"
            )

        # En dry-run el problema se avisa pero no corta: el sentido del dry-run
        # es poder ver que saldria antes de terminar de configurar el correo.
        problema = self.problema_de_configuracion()
        if problema and not dry_run:
            log.warning("digest_mal_configurado", motivo=problema)
            return DigestResult(estado="error", error=problema, detalle=problema)

        seleccion = sorted(
            analizados,
            key=lambda p: p.analysis.valoracion,  # type: ignore[union-attr]
            reverse=True,
        )[: max(1, self.config.max_items)]
        restantes = len(analizados) - len(seleccion)

        dia = fecha or datetime.now().astimezone().strftime("%Y-%m-%d")
        asunto = asunto_digest(seleccion, dia)
        shortcodes = [p.item.shortcode for p in seleccion]
        detalle = f"{len(seleccion)} elemento(s)" + (
            f"; quedan {restantes} para el proximo digest" if restantes else ""
        )

        if dry_run:
            return DigestResult(
                estado="dry_run",
                asunto=asunto,
                shortcodes=shortcodes,
                detalle=detalle + (f"; ojo: {problema}" if problema else ""),
                error=problema,
            )

        cuerpo: dict[str, Any] = {
            "from": self.config.from_address,
            "to": [self.config.to_address],
            "subject": asunto,
            "html": render_html(seleccion, dia),
            "text": render_texto(seleccion, dia),
        }

        adjunto = self._adjunto_catalogo(catalogo, dia)
        if adjunto:
            cuerpo["attachments"] = [adjunto]

        try:
            respuesta = httpx.post(
                RESEND_URL,
                json=cuerpo,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        except Exception as exc:  # noqa: BLE001
            error = f"no se pudo contactar a Resend: {exc}"[:300]
            log.warning("digest_sin_red", error=error)
            return DigestResult(
                estado="error", asunto=asunto, error=error, detalle=error
            )

        if respuesta.status_code not in (200, 201, 202):
            error = f"Resend respondio {respuesta.status_code}: {respuesta.text[:200]}"
            log.warning("digest_rechazado", status=respuesta.status_code, error=error)
            return DigestResult(
                estado="error", asunto=asunto, error=error, detalle=error
            )

        try:
            message_id = str(respuesta.json().get("id", ""))
        except ValueError:
            message_id = ""

        log.info(
            "digest_enviado",
            elementos=len(seleccion),
            destino=self.config.to_address,
            message_id=message_id,
        )
        return DigestResult(
            estado="sent",
            asunto=asunto,
            message_id=message_id,
            shortcodes=shortcodes,
            detalle=detalle,
        )
