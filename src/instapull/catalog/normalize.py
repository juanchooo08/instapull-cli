"""Clave canonica de una herramienta, para no catalogarla dos veces.

El modelo escribe el mismo producto de mil formas: "Eleven Labs", "ElevenLabs",
"elevenlabs.io", "ElevenLabs (voz)". Todas tienen que colapsar a la misma clave
o el catalogo se llena de duplicados y cada post vuelve a "descubrir" lo mismo.
"""

from __future__ import annotations

import re
import unicodedata

# Sufijos de dominio que no distinguen al producto: cursor.com == Cursor
_TLDS = (
    "com",
    "ai",
    "io",
    "dev",
    "app",
    "co",
    "net",
    "org",
    "so",
    "sh",
    "xyz",
    "tools",
    "cloud",
)

# Palabras que el modelo pega al nombre y no son parte de el
_RUIDO_PEGADO = ("app", "ai", "io", "official", "oficial")

# Entradas que no son una herramienta: se descartan del catalogo
_NO_ES_HERRAMIENTA = {
    "ia",
    "ai",
    "inteligencia artificial",
    "artificial intelligence",
    "chatbot",
    "prompt",
    "prompts",
    "api",
    "sdk",
    "app",
    "aplicacion",
    "software",
    "herramienta",
    "herramientas",
    "tool",
    "tools",
    "web",
    "internet",
    "n/a",
    "ninguna",
    "ninguno",
    "varios",
    "otros",
    "etc",
}

# Alias que la normalizacion mecanica no puede unir sola
_ALIAS = {
    "chatgpt": "openaichatgpt",
    "gpt4": "openaichatgpt",
    "gpt4o": "openaichatgpt",
    "gpt5": "openaichatgpt",
    "claude": "claude",
    "claudecode": "claudecode",
    "anthropicclaude": "claude",
    "geminigoogle": "gemini",
    "googlegemini": "gemini",
    "vscode": "visualstudiocode",
    "makecom": "make",
    "integromat": "make",
    "midjourney": "midjourney",
    "stablediffusionxl": "stablediffusion",
    "sdxl": "stablediffusion",
    "hugginface": "huggingface",
}

_PARENTESIS = re.compile(r"\([^)]*\)")
_ESQUEMA = re.compile(r"^[a-z]+://")
_NO_ALFANUM = re.compile(r"[^a-z0-9]+")


def _sin_acentos(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def nombre_legible(bruto: str) -> str:
    """El nombre tal como se muestra: limpio, pero conservando mayusculas."""
    texto = _PARENTESIS.sub(" ", bruto or "").strip()
    texto = _ESQUEMA.sub("", texto)
    texto = texto.strip(" \t\r\n-–—·:;,.\"'“”«»()[]")
    return re.sub(r"\s{2,}", " ", texto)


def canonicalizar(bruto: str) -> str:
    """Clave estable de una herramienta. Cadena vacia si no sirve como clave.

    Ejemplos:
        "Eleven Labs"      -> "elevenlabs"
        "elevenlabs.io"    -> "elevenlabs"
        "ElevenLabs (voz)" -> "elevenlabs"
        "https://n8n.io/"  -> "n8n"
    """
    texto = nombre_legible(bruto).lower()
    if not texto:
        return ""

    texto = _sin_acentos(texto)

    # De una URL solo interesa el dominio, sin www ni ruta
    if "/" in texto:
        texto = texto.split("/")[0]
    if texto.startswith("www."):
        texto = texto[4:]

    if texto in _NO_ES_HERRAMIENTA:
        return ""

    # Se quita el TLD final, pero solo si queda algo antes
    partes = texto.split(".")
    while len(partes) > 1 and partes[-1] in _TLDS:
        partes = partes[:-1]
    texto = ".".join(partes)

    clave = _NO_ALFANUM.sub("", texto)
    if not clave:
        return ""

    # "cursorapp" -> "cursor", pero nunca vaciar el nombre entero
    for sufijo in _RUIDO_PEGADO:
        if clave.endswith(sufijo) and len(clave) > len(sufijo) + 2:
            clave = clave[: -len(sufijo)]
            break

    clave = _ALIAS.get(clave, clave)

    if len(clave) < 2 or clave.isdigit():
        return ""
    if clave in {_NO_ALFANUM.sub("", n) for n in _NO_ES_HERRAMIENTA}:
        return ""
    return clave


def es_ruido(bruto: str) -> bool:
    """True si la entrada no merece una fila en el catalogo."""
    return not canonicalizar(bruto)
