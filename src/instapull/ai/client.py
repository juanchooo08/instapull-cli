"""Cliente de IA compatible con el formato OpenAI, apuntando a OpenRouter.

Cambiar de modelo es editar `ai.model` en config.yaml: nada mas depende del
proveedor concreto.
"""

from __future__ import annotations

import base64
import json
import random
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from ..config import AIConfig
from ..logging_setup import get_logger

log = get_logger(__name__)


class AIError(RuntimeError):
    """El modelo no pudo responder ni con el fallback."""


def imagen_a_data_url(ruta: Path) -> str:
    """Codifica una imagen local como data URL para el mensaje multimodal."""
    datos = ruta.read_bytes()
    extension = ruta.suffix.lower().lstrip(".") or "jpeg"
    mime = "image/png" if extension == "png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(datos).decode('ascii')}"


def extraer_json(texto: str) -> dict[str, Any]:
    """Saca el primer objeto JSON del texto, tolerando ```json ... ``` y prosa."""
    if not texto:
        raise ValueError("respuesta vacia")

    limpio = texto.strip()
    valla = re.search(r"```(?:json)?\s*(.+?)```", limpio, re.S)
    if valla:
        limpio = valla.group(1).strip()

    try:
        datos = json.loads(limpio)
        if isinstance(datos, dict):
            return datos
    except json.JSONDecodeError:
        pass

    # Ultimo recurso: recortar del primer { al ultimo }
    inicio, fin = limpio.find("{"), limpio.rfind("}")
    if inicio != -1 and fin > inicio:
        datos = json.loads(limpio[inicio : fin + 1])
        if isinstance(datos, dict):
            return datos
    raise ValueError(f"la respuesta no contiene JSON valido: {texto[:200]}")


def _a_bloques_claude(contenido: Any) -> list[dict[str, Any]]:
    """Convierte el contenido estilo OpenAI (texto + image_url) a bloques de Claude."""
    if isinstance(contenido, str):
        return [{"type": "text", "text": contenido}]
    bloques: list[dict[str, Any]] = []
    for parte in contenido:
        if parte.get("type") == "text":
            bloques.append({"type": "text", "text": parte["text"]})
        elif parte.get("type") == "image_url":
            url = parte["image_url"]["url"]
            cabecera, _, datos = url.partition(",")
            mime = cabecera.removeprefix("data:").split(";")[0] or "image/jpeg"
            bloques.append(
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": datos}}
            )
    return bloques


class AIClient:
    """Envoltura sobre el SDK de OpenAI con reintentos y modelo de respaldo.

    Con `ai.provider: claude-cli` llama a `claude -p` y usa la suscripcion de
    Claude en vez de OpenRouter.
    """

    def __init__(self, config: AIConfig, api_key: str) -> None:
        self.config = config
        self.ultimo_modelo = ""
        self.ultimos_tokens = 0
        if config.provider == "claude-cli":
            self._claude = shutil.which("claude")
            if not self._claude:
                raise AIError("No encuentro el binario `claude` en el PATH.")
            self.modelo = config.claude_model
            self.modelo_fallback = ""
            return
        if not api_key:
            raise AIError(
                "Falta OPENROUTER_API_KEY. Defini la variable de entorno antes de correr."
            )
        from openai import OpenAI

        self.modelo = config.model
        self.modelo_fallback = config.model_fallback
        self._client = OpenAI(
            api_key=api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            default_headers={
                "HTTP-Referer": "https://github.com/instapull",
                "X-Title": "InstaPull",
            },
        )

    # --- llamadas -----------------------------------------------------

    def _llamar_claude(
        self, modelo: str, mensajes: list[dict[str, Any]], json_mode: bool
    ) -> str:
        sistema = "\n\n".join(m["content"] for m in mensajes if m["role"] == "system")
        if json_mode:
            sistema += "\n\nResponde unicamente con un objeto JSON valido, sin texto extra."
        entrada = "".join(
            json.dumps(
                {"type": "user", "message": {"role": "user", "content": _a_bloques_claude(m["content"])}}
            )
            + "\n"
            for m in mensajes
            if m["role"] == "user"
        )
        comando = [
            self._claude, "-p",
            "--model", modelo,
            "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose",
            "--tools", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--system-prompt", sistema,
        ]
        # cwd vacio: que no cargue el CLAUDE.md de ningun proyecto
        with tempfile.TemporaryDirectory() as vacio:
            proceso = subprocess.run(
                comando, input=entrada, capture_output=True, text=True,
                cwd=vacio, timeout=self.config.timeout_seconds * 3,
            )
        resultado: dict[str, Any] = {}
        for linea in proceso.stdout.splitlines():
            try:
                evento = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if isinstance(evento, dict) and evento.get("type") == "result":
                resultado = evento
        if not resultado or resultado.get("is_error"):
            detalle = resultado.get("result") or proceso.stderr[-300:] or "sin salida"
            raise RuntimeError(f"claude -p fallo: {detalle}")
        uso = resultado.get("usage", {})
        self.ultimos_tokens = sum(
            int(uso.get(k, 0) or 0)
            for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        )
        self.ultimo_modelo = f"claude-cli:{modelo}"
        return str(resultado.get("result", "")).strip()

    def _llamar(
        self, modelo: str, mensajes: list[dict[str, Any]], json_mode: bool
    ) -> str:
        if self.config.provider == "claude-cli":
            return self._llamar_claude(modelo, mensajes, json_mode)
        extra: dict[str, Any] = {}
        if json_mode:
            extra["response_format"] = {"type": "json_object"}
        respuesta = self._client.chat.completions.create(
            model=modelo,
            messages=mensajes,  # type: ignore[arg-type]
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            **extra,
        )
        uso = getattr(respuesta, "usage", None)
        self.ultimos_tokens = int(getattr(uso, "total_tokens", 0) or 0)
        self.ultimo_modelo = modelo
        return (respuesta.choices[0].message.content or "").strip()

    def chat(self, mensajes: list[dict[str, Any]], json_mode: bool = False) -> str:
        """Llama al modelo primario y, si falla, al de respaldo."""
        errores: list[str] = []
        for modelo in (self.modelo, self.modelo_fallback):
            if not modelo:
                continue
            for intento in range(1, self.config.max_retries + 1):
                try:
                    return self._llamar(modelo, mensajes, json_mode)
                except Exception as exc:  # noqa: BLE001
                    errores.append(f"{modelo}: {exc}")
                    recuperable = any(
                        s in str(exc).lower()
                        for s in ("429", "rate", "timeout", "500", "502", "503", "529")
                    )
                    if not recuperable or intento == self.config.max_retries:
                        log.warning("modelo_fallo", modelo=modelo, error=str(exc)[:200])
                        break
                    espera = 3.0 * (2 ** (intento - 1)) * random.uniform(0.8, 1.3)
                    log.warning(
                        "modelo_reintento",
                        modelo=modelo,
                        intento=intento,
                        espera_s=round(espera, 1),
                    )
                    time.sleep(espera)
            if modelo == self.modelo and self.modelo_fallback:
                log.warning("usando_modelo_fallback", fallback=self.modelo_fallback)
        raise AIError("Ningun modelo respondio. Detalle: " + " | ".join(errores[-3:]))

    def chat_json(self, mensajes: list[dict[str, Any]]) -> dict[str, Any]:
        """Como `chat`, pero exige y valida un objeto JSON."""
        texto = self.chat(mensajes, json_mode=True)
        return extraer_json(texto)
