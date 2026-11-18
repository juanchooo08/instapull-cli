"""Extraccion de URLs y resolucion de redirecciones."""

from __future__ import annotations

import httpx
import pytest
import respx

from instapull.config import LinksConfig
from instapull.links.resolver import (
    es_acortador,
    extraer_urls,
    resolver_enlace,
    resolver_enlaces,
)


def test_extrae_urls_con_y_sin_esquema() -> None:
    texto = "Mira https://github.com/org/repo y tambien www.herramienta.ai/precios"
    urls = extraer_urls(texto)
    assert "https://github.com/org/repo" in urls
    assert "https://www.herramienta.ai/precios" in urls


def test_ignora_dominios_de_instagram() -> None:
    texto = "https://www.instagram.com/p/ABC/ y https://scontent.cdninstagram.com/x.jpg"
    assert extraer_urls(texto) == []


def test_no_duplica_ni_arrastra_puntuacion() -> None:
    texto = "Link: https://ejemplo.test/x. Repetido: https://ejemplo.test/x."
    assert extraer_urls(texto) == ["https://ejemplo.test/x"]


def test_texto_vacio() -> None:
    assert extraer_urls("") == []


def test_reconoce_acortadores() -> None:
    assert es_acortador("https://bit.ly/abc")
    assert es_acortador("https://mnch.at/xyz")
    assert not es_acortador("https://github.com/org/repo")


@respx.mock
def test_sigue_la_redireccion_hasta_el_destino() -> None:
    respx.get("https://bit.ly/abc").mock(
        return_value=httpx.Response(301, headers={"Location": "https://ejemplo.test/final"})
    )
    respx.get("https://ejemplo.test/final").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><title>Herramienta X</title><body>Genera videos con IA</body></html>",
        )
    )

    resultado = resolver_enlace("https://bit.ly/abc", LinksConfig())
    assert resultado.url_final == "https://ejemplo.test/final"
    assert resultado.titulo == "Herramienta X"
    assert "Genera videos" in resultado.extracto
    assert resultado.error is None


@respx.mock
def test_lee_el_readme_de_un_repo_de_github() -> None:
    respx.get("https://github.com/org/repo").mock(
        return_value=httpx.Response(
            200, headers={"content-type": "text/html"}, text="<html></html>"
        )
    )
    respx.get("https://api.github.com/repos/org/repo").mock(
        return_value=httpx.Response(200, json={"description": "Agente de research"})
    )
    respx.get("https://api.github.com/repos/org/repo/readme").mock(
        return_value=httpx.Response(200, text="# Repo\nInstalacion con pip.")
    )

    resultado = resolver_enlace("https://github.com/org/repo", LinksConfig())
    assert resultado.tipo == "github_repo"
    assert resultado.titulo == "org/repo"
    assert "Agente de research" in resultado.extracto
    assert "Instalacion con pip" in resultado.extracto


@respx.mock
def test_un_enlace_caido_no_rompe_nada() -> None:
    respx.get("https://roto.test/x").mock(side_effect=httpx.ConnectError("sin conexion"))
    resultado = resolver_enlace("https://roto.test/x", LinksConfig())
    assert resultado.error is not None
    assert resultado.url_original == "https://roto.test/x"


@pytest.mark.parametrize(
    "url,tipo",
    [
        ("https://github.com/org/repo", "github_repo"),
        ("https://youtu.be/abc", "video"),
        ("https://docs.ejemplo.test/guia", "doc"),
        ("https://herramienta.test", "herramienta"),
    ],
)
def test_clasifica_sin_red(url: str, tipo: str) -> None:
    resultado = resolver_enlaces([url], LinksConfig(resolve_enabled=False))[0]
    assert resultado.tipo == tipo
