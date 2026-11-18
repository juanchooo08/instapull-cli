"""Deteccion de la consigna 'comenta X' en captions reales."""

from __future__ import annotations

import pytest

from instapull.ai.keyword import detectar_keyword, detectar_por_regex

CON_CONSIGNA = [
    ('Comenta "AGENTE" y te mando el repo por DM', "AGENTE"),
    ("Comentá RAG y te lo envío por privado", "RAG"),
    ("Comment WORKFLOW and I'll send you the link", "WORKFLOW"),
    ("Escribí la palabra CURSOR abajo y revisa tus mensajes", "CURSOR"),
    ("Deja 'N8N' en los comentarios y te llega el template", "N8N"),
    ("Comenta CLAUDE5 para recibir el prompt completo por mensaje directo", "CLAUDE5"),
]

SIN_CONSIGNA = [
    "Comenta que te pareció este video",
    "Escribime si tenes dudas",
    "Mira este reel hasta el final",
    "",
    "Guarda este post para no perderlo",
    "Comment below what you think",
]


@pytest.mark.parametrize("caption,esperada", CON_CONSIGNA)
def test_detecta_consigna(caption: str, esperada: str) -> None:
    deteccion = detectar_por_regex(caption)
    assert deteccion.pide_comentario, caption
    assert deteccion.palabra == esperada


@pytest.mark.parametrize("caption", SIN_CONSIGNA)
def test_ignora_invitaciones_a_opinar(caption: str) -> None:
    assert not detectar_por_regex(caption).pide_comentario, caption


def test_limpia_comillas_y_puntuacion() -> None:
    deteccion = detectar_por_regex('Comenta "MCP" y te lo mando')
    assert deteccion.palabra == "MCP"


def test_no_llama_a_la_ia_si_el_regex_esta_seguro() -> None:
    class ClienteEspia:
        def __init__(self) -> None:
            self.llamadas = 0

        def chat_json(self, _mensajes):  # noqa: ANN001, ANN202
            self.llamadas += 1
            return {}

    espia = ClienteEspia()
    deteccion = detectar_keyword('Comenta "AGENTE" y te lo envio', espia)
    assert deteccion.palabra == "AGENTE"
    assert espia.llamadas == 0


def test_usa_la_ia_cuando_el_regex_no_alcanza() -> None:
    class ClienteFalso:
        def chat_json(self, _mensajes):  # noqa: ANN001, ANN202
            return {"pide_comentario": True, "palabra": "FLUJO", "confianza": 0.9}

    caption = "Queres el sistema? Ya sabes que hacer en los comentarios, te llega por DM"
    deteccion = detectar_keyword(caption, ClienteFalso())
    assert deteccion.pide_comentario
    assert deteccion.palabra == "FLUJO"
    assert deteccion.fuente == "ia"


def test_descarta_palabra_invalida_devuelta_por_la_ia() -> None:
    class ClienteFalso:
        def chat_json(self, _mensajes):  # noqa: ANN001, ANN202
            return {"pide_comentario": True, "palabra": "que", "confianza": 0.9}

    deteccion = detectar_keyword(
        "Comenta lo que quieras, te mando algo por dm", ClienteFalso()
    )
    assert not deteccion.pide_comentario
    assert deteccion.palabra is None


def test_ia_no_se_invoca_si_no_hay_pistas() -> None:
    class ClienteEspia:
        def __init__(self) -> None:
            self.llamadas = 0

        def chat_json(self, _mensajes):  # noqa: ANN001, ANN202
            self.llamadas += 1
            return {"pide_comentario": True, "palabra": "X"}

    espia = ClienteEspia()
    detectar_keyword("Un reel sobre modelos de difusion", espia)
    assert espia.llamadas == 0
