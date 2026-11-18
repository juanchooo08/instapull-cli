"""Que exige cada post y por que via conviene ir."""

from __future__ import annotations

from instapull.ai.requisitos import detectar_requisitos
from instapull.links.resolver import extraer_urls
from instapull.models import PostRequisitos


def _req(caption: str) -> PostRequisitos:
    return detectar_requisitos(caption, extraer_urls, cliente=None)


def test_si_el_enlace_esta_en_el_post_no_se_interactua() -> None:
    req = _req("Toda la guia gratis aca: https://ejemplo.dev/guia")
    assert req.via == "directa"
    assert req.requisitos == []
    assert req.urls_directas == ["https://ejemplo.dev/guia"]


def test_un_enlace_a_instagram_no_cuenta_como_via_directa() -> None:
    req = _req('Comenta "GUIA" y te la mando. https://www.instagram.com/cuenta/')
    assert req.via == "comentario"
    assert req.palabra == "GUIA"


def test_detecta_que_hay_que_seguir_la_cuenta() -> None:
    req = _req('Sigueme y comenta "AGENTE" para recibir el flujo.')
    assert req.via == "comentario"
    assert req.pide("seguir") and req.pide("comentar")


def test_detecta_like_y_guardar() -> None:
    req = _req('Dale like, guarda este post y comenta "N8N" para el link.')
    assert set(req.requisitos) >= {"comentar", "like", "guardar"}


def test_follow_en_ingles() -> None:
    assert _req('Follow me and comment "STACK" to get it').pide("seguir")


def test_un_post_sin_consigna_ni_enlace_no_exige_nada() -> None:
    req = _req("Tres ideas para mejorar tus prompts de hoy.")
    assert req.via == "ninguna"
    assert req.requisitos == []


def test_las_exigencias_se_anotan_aunque_la_via_sea_directa() -> None:
    # No hay que cumplirlas: el recurso ya esta a la vista
    req = _req("Sigueme para mas. Guia: https://ejemplo.dev/x")
    assert req.via == "directa"
    assert req.requisitos == []
