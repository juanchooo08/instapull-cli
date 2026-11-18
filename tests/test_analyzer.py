"""Validacion y normalizacion de la respuesta del modelo."""

from __future__ import annotations

import pytest

from instapull.ai.analyzer import analizar_elemento
from instapull.ai.client import extraer_json
from instapull.models import Analysis, Categoria, ProcessedItem, ResolvedLink, SavedItem


class ClienteFalso:
    """Sustituto de AIClient que devuelve una respuesta fija."""

    def __init__(self, datos: dict) -> None:
        self.datos = datos
        self.ultimo_modelo = "modelo/prueba"
        self.ultimos_tokens = 1234
        self.mensajes_recibidos: list = []

    def chat_json(self, mensajes):  # noqa: ANN001, ANN202
        self.mensajes_recibidos = mensajes
        return self.datos


RESPUESTA_OK = {
    "titulo": "Agente de investigacion con LangGraph",
    "resumen": "Un agente que busca y resume papers. Corre local con Ollama.",
    "categoria": "repo de GitHub",
    "herramientas": ["LangGraph", "Ollama"],
    "repos": ["org/deep-research"],
    "enlaces": ["https://github.com/org/deep-research"],
    "valoracion": 5,
    "etiquetas": ["agentes", "rag"],
}


def _procesado() -> ProcessedItem:
    return ProcessedItem(
        item=SavedItem(
            shortcode="TEST001",
            caption="Comenta AGENTE",
            author="cuenta_demo",
            permalink="https://www.instagram.com/p/TEST001/",
        )
    )


def test_analiza_y_completa_metadatos() -> None:
    cliente = ClienteFalso(RESPUESTA_OK)
    analisis = analizar_elemento(cliente, _procesado())  # type: ignore[arg-type]
    assert analisis.titulo.startswith("Agente")
    assert analisis.categoria is Categoria.REPO_GITHUB
    assert analisis.valoracion == 5
    assert analisis.modelo == "modelo/prueba"
    assert analisis.tokens == 1234


def test_agrega_los_enlaces_resueltos_al_analisis() -> None:
    procesado = _procesado()
    procesado.links = [
        ResolvedLink(
            url_original="https://bit.ly/abc",
            url_final="https://github.com/org/otro",
            tipo="github_repo",
        )
    ]
    analisis = analizar_elemento(ClienteFalso(RESPUESTA_OK), procesado)  # type: ignore[arg-type]
    assert "https://github.com/org/otro" in analisis.enlaces


def test_valoracion_fuera_de_rango_se_acota() -> None:
    assert Analysis.model_validate({"valoracion": 9}).valoracion == 5
    assert Analysis.model_validate({"valoracion": -3}).valoracion == 1
    assert Analysis.model_validate({"valoracion": "cuatro"}).valoracion == 1
    assert Analysis.model_validate({"valoracion": "4"}).valoracion == 4


def test_categoria_desconocida_cae_en_otro() -> None:
    assert Analysis.model_validate({"categoria": "cosa rara"}).categoria is Categoria.OTRO
    assert (
        Analysis.model_validate({"categoria": "GitHub Repo"}).categoria
        is Categoria.REPO_GITHUB
    )


def test_listas_con_formas_raras_se_normalizan() -> None:
    analisis = Analysis.model_validate(
        {
            "herramientas": [{"nombre": "Cursor"}, "Claude", "", None],
            "repos": "org/repo",
            "etiquetas": None,
        }
    )
    assert analisis.herramientas == ["Cursor", "Claude"]
    assert analisis.repos == ["org/repo"]
    assert analisis.etiquetas == []


def test_extraer_json_tolera_bloques_de_codigo_y_prosa() -> None:
    assert extraer_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extraer_json('Aca tenes: {"a": 2} listo') == {"a": 2}
    with pytest.raises(ValueError):
        extraer_json("no hay json aca")
