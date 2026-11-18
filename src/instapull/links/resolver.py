"""Extraccion de URLs, expansion de redirecciones y lectura del destino."""

from __future__ import annotations

import re
from typing import Iterable

import httpx

from ..config import LinksConfig
from ..logging_setup import get_logger
from ..models import ResolvedLink

log = get_logger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# URLs con esquema, o dominios sueltos tipo "github.com/org/repo"
_RE_URL = re.compile(
    r"""(?xi)
    \b(
        https?://[^\s<>"'\]\)]+
        |
        (?:www\.|[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>"'\]\)]*)?
    )
    """
)

# Dominios que casi nunca son el recurso buscado
_IGNORADOS = (
    "instagram.com",
    "cdninstagram.com",
    "fbcdn.net",
    "facebook.com",
    "w3.org",
    "schema.org",
)

_ACORTADORES = (
    "bit.ly",
    "tinyurl.com",
    "t.co",
    "lnkd.in",
    "rb.gy",
    "cutt.ly",
    "manychat.com",
    "mnch.at",
    "linktr.ee",
    "beacons.ai",
    "shorturl.at",
)


def _limpiar(url: str) -> str:
    url = url.strip().rstrip(".,;:!?)]}\"'")
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def extraer_urls(texto: str, limite: int = 20) -> list[str]:
    """Todas las URLs utiles de un texto, sin duplicados y en orden de aparicion."""
    if not texto:
        return []
    vistas: set[str] = set()
    salida: list[str] = []
    for coincidencia in _RE_URL.finditer(texto):
        url = _limpiar(coincidencia.group(1))
        dominio = url.split("//", 1)[-1].split("/", 1)[0].lower()
        if any(ign in dominio for ign in _IGNORADOS):
            continue
        if "." not in dominio:
            continue
        if url in vistas:
            continue
        vistas.add(url)
        salida.append(url)
        if len(salida) >= limite:
            break
    return salida


def es_acortador(url: str) -> bool:
    dominio = url.split("//", 1)[-1].split("/", 1)[0].lower()
    return any(a in dominio for a in _ACORTADORES)


def _clasificar(url: str) -> str:
    dominio = url.split("//", 1)[-1].split("/", 1)[0].lower()
    if "github.com" in dominio:
        return "github_repo"
    if any(v in dominio for v in ("youtube.com", "youtu.be", "vimeo.com")):
        return "video"
    if any(d in dominio for d in ("docs.", "readthedocs", "notion.so", "gitbook")):
        return "doc"
    if any(a in dominio for a in _ACORTADORES):
        return "otro"
    return "herramienta"


def _texto_de_html(html: str, limite: int) -> tuple[str, str]:
    """Devuelve (titulo, extracto de texto plano) de un documento HTML."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return "", html[:limite]

    sopa = BeautifulSoup(html, "html.parser")
    titulo = (sopa.title.string or "").strip() if sopa.title else ""
    for etiqueta in sopa(["script", "style", "noscript", "svg"]):
        etiqueta.decompose()
    texto = " ".join(sopa.get_text(" ", strip=True).split())
    return titulo, texto[:limite]


def _readme_de_github(url: str, cliente: httpx.Client, limite: int) -> tuple[str, str]:
    """Descripcion + README del repo via API publica de GitHub."""
    partes = url.split("github.com/", 1)[-1].strip("/").split("/")
    if len(partes) < 2:
        return "", ""
    owner, repo = partes[0], partes[1].removesuffix(".git")
    try:
        meta = cliente.get(f"https://api.github.com/repos/{owner}/{repo}")
        descripcion = ""
        if meta.status_code == 200:
            datos = meta.json()
            descripcion = (datos.get("description") or "").strip()
        readme = cliente.get(
            f"https://api.github.com/repos/{owner}/{repo}/readme",
            headers={"Accept": "application/vnd.github.raw"},
        )
        cuerpo = readme.text if readme.status_code == 200 else ""
        return f"{owner}/{repo}", f"{descripcion}\n\n{cuerpo}".strip()[:limite]
    except Exception as exc:  # noqa: BLE001
        log.debug("github_api_fallo", url=url, error=str(exc)[:200])
        return f"{owner}/{repo}", ""


def resolver_enlace(url: str, config: LinksConfig) -> ResolvedLink:
    """Sigue redirecciones y trae el contenido del destino."""
    resultado = ResolvedLink(url_original=url, url_final=url, tipo=_clasificar(url))
    try:
        with httpx.Client(
            timeout=config.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        ) as cliente:
            respuesta = cliente.get(url)
            resultado.url_final = str(respuesta.url)
            resultado.tipo = _clasificar(resultado.url_final)

            if resultado.tipo == "github_repo":
                titulo, cuerpo = _readme_de_github(
                    resultado.url_final, cliente, config.excerpt_chars
                )
                resultado.titulo = titulo
                resultado.extracto = cuerpo
                if cuerpo:
                    return resultado

            tipo_contenido = respuesta.headers.get("content-type", "")
            if "html" in tipo_contenido:
                titulo, extracto = _texto_de_html(respuesta.text, config.excerpt_chars)
                resultado.titulo = resultado.titulo or titulo
                resultado.extracto = extracto
            elif "text" in tipo_contenido or "json" in tipo_contenido:
                resultado.extracto = respuesta.text[: config.excerpt_chars]
    except Exception as exc:  # noqa: BLE001
        resultado.error = str(exc)[:300]
        log.warning("enlace_no_resuelto", url=url, error=resultado.error)
    return resultado


def resolver_enlaces(urls: Iterable[str], config: LinksConfig) -> list[ResolvedLink]:
    """Resuelve varios enlaces respetando el tope configurado."""
    if not config.resolve_enabled:
        return [
            ResolvedLink(url_original=u, url_final=u, tipo=_clasificar(u)) for u in urls
        ]

    salida: list[ResolvedLink] = []
    for url in list(urls)[: config.max_links_per_item]:
        salida.append(resolver_enlace(url, config))
    if salida:
        log.info("enlaces_resueltos", cantidad=len(salida))
    return salida
