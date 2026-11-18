"""Paginacion de la coleccion, topes de comentarios y pendientes de DM."""

from __future__ import annotations

from pathlib import Path

import pytest

from instapull.config import Config
from instapull.db import Database
from instapull.instagram.collection import iter_collection
from instapull.instagram.comments import (
    ContadorComentarios,
    LimiteComentarios,
    publicar_comentario,
)
from instapull.instagram.ratelimit import ActionBlocked
from instapull.models import DmResult, ItemStatus, MediaType, SavedItem, utcnow_iso


TAMANO_PAGINA = 30


def media_cruda(pk: int) -> dict:
    """Item crudo de `feed/collection/{id}/`, como lo devuelve la API privada."""
    return {
        "media": {
            "pk": pk,
            "id": f"{pk}_9",
            "code": f"SC{pk:03d}",
            "media_type": 1,
            "taken_at": 1773446400,
            "user": {"pk": 9, "username": "cuenta_demo"},
            "caption": {"text": "caption de prueba"},
            "image_versions2": {
                "candidates": [{"url": "https://ejemplo.test/x.jpg", "width": 1, "height": 1}]
            },
        }
    }


class ColeccionFalsa:
    """Cliente que pagina una coleccion de N elementos con cursor `max_id`."""

    def __init__(self, total: int) -> None:
        self.medias = [media_cruda(i) for i in range(1, total + 1)]
        self.cursores_pedidos: list[str] = []

    @property
    def paginas_pedidas(self) -> int:
        return len(self.cursores_pedidos)

    def collections(self):  # noqa: ANN201
        return [type("C", (), {"id": "col1", "name": "AI"})()]

    def private_request(self, endpoint: str, params: dict | None = None):  # noqa: ANN201
        assert endpoint == "feed/collection/col1/"
        max_id = (params or {}).get("max_id", "")
        self.cursores_pedidos.append(max_id)
        inicio = int(max_id) if max_id else 0
        fin = inicio + TAMANO_PAGINA
        hay_mas = fin < len(self.medias)
        return {
            "items": self.medias[inicio:fin],
            "more_available": hay_mas,
            "next_max_id": str(fin) if hay_mas else None,
        }


class SesionFalsa:
    def __init__(self, cliente) -> None:  # noqa: ANN001
        self.client = cliente


@pytest.fixture
def config_rapida() -> Config:
    """Config sin pausas, para que los tests no duerman."""
    cfg = Config()
    cfg.instagram.request_delay_seconds = (0.0, 0.0)
    cfg.comments.action_delay_seconds = (0.0, 0.0)
    return cfg


def test_pagina_hasta_completar_el_tope(config_rapida: Config) -> None:
    """Con casi todo ya procesado, hay que pasar de la primera pagina."""
    cliente = ColeccionFalsa(total=90)
    procesados = {f"SC{i:03d}" for i in range(1, 51)}

    obtenidos = [
        item.shortcode
        for item, _ in iter_collection(
            SesionFalsa(cliente),  # type: ignore[arg-type]
            config_rapida,
            limite=5,
            omitir=lambda sc: sc in procesados,
        )
    ]
    assert obtenidos == ["SC051", "SC052", "SC053", "SC054", "SC055"]
    assert cliente.paginas_pedidas >= 2


def test_se_detiene_al_agotar_la_coleccion(config_rapida: Config) -> None:
    cliente = ColeccionFalsa(total=7)
    obtenidos = list(
        iter_collection(SesionFalsa(cliente), config_rapida, limite=50)  # type: ignore[arg-type]
    )
    assert len(obtenidos) == 7
    assert cliente.paginas_pedidas == 1  # 7 < TAMANO_PAGINA: no pide otra


def test_respeta_el_tope_sin_paginar_de_mas(config_rapida: Config) -> None:
    cliente = ColeccionFalsa(total=TAMANO_PAGINA * 3)
    obtenidos = list(
        iter_collection(SesionFalsa(cliente), config_rapida, limite=3)  # type: ignore[arg-type]
    )
    assert len(obtenidos) == 3
    assert cliente.paginas_pedidas == 1


def test_sigue_el_cursor_max_id_entre_paginas(config_rapida: Config) -> None:
    """Dos paginas: la segunda se pide con el `next_max_id` de la primera."""
    cliente = ColeccionFalsa(total=TAMANO_PAGINA + 12)
    obtenidos = [
        item.shortcode
        for item, _ in iter_collection(
            SesionFalsa(cliente), config_rapida, limite=100  # type: ignore[arg-type]
        )
    ]
    assert cliente.cursores_pedidos == ["", str(TAMANO_PAGINA)]
    assert len(obtenidos) == TAMANO_PAGINA + 12
    assert len(set(obtenidos)) == len(obtenidos)
    assert obtenidos[0] == "SC001" and obtenidos[-1] == "SC042"


def test_corta_si_la_api_repite_el_cursor(config_rapida: Config) -> None:
    cliente = ColeccionFalsa(total=5)
    cliente.private_request = lambda *_a, **_k: {  # type: ignore[method-assign]
        "items": cliente.medias,
        "more_available": True,
        "next_max_id": "X",
    }
    obtenidos = list(
        iter_collection(SesionFalsa(cliente), config_rapida, limite=100)  # type: ignore[arg-type]
    )
    assert len(obtenidos) == 5


# --- comentarios ---------------------------------------------------------


class ClienteComentarios:
    def __init__(self, excepcion: Exception | None = None) -> None:
        self.excepcion = excepcion
        self.comentarios: list[tuple[str, str]] = []

    def media_comment(self, media_id: str, text: str):  # noqa: ANN201
        if self.excepcion:
            raise self.excepcion
        self.comentarios.append((media_id, text))
        return type("Comment", (), {"pk": "c123"})()


def _item(shortcode: str = "TEST001") -> SavedItem:
    return SavedItem(
        shortcode=shortcode,
        media_id="123",
        author="cuenta_demo",
        caption="Comenta LINK",
        media_type=MediaType.IMAGE,
    )


def test_comenta_una_sola_vez(tmp_path: Path, config_rapida: Config) -> None:
    cliente = ClienteComentarios()
    sesion = SesionFalsa(cliente)
    with Database(tmp_path / "t.db") as db:
        item = _item()
        db.upsert_item(item)
        contador = ContadorComentarios(5)

        primero = publicar_comentario(sesion, db, config_rapida, item, "LINK", contador)  # type: ignore[arg-type]
        assert primero.estado == "commented"
        assert contador.publicados == 1

        # Segunda pasada sobre el mismo post: no vuelve a comentar
        segundo = publicar_comentario(sesion, db, config_rapida, item, "LINK", contador)  # type: ignore[arg-type]
        assert len(cliente.comentarios) == 1
        assert contador.publicados == 1
        assert segundo.commented_at is not None


def test_el_tope_por_corrida_corta(tmp_path: Path, config_rapida: Config) -> None:
    cliente = ClienteComentarios()
    sesion = SesionFalsa(cliente)
    with Database(tmp_path / "t.db") as db:
        contador = ContadorComentarios(2)
        for i in range(2):
            item = _item(f"SC{i}")
            db.upsert_item(item)
            publicar_comentario(sesion, db, config_rapida, item, "LINK", contador)  # type: ignore[arg-type]

        tercero = _item("SC2")
        db.upsert_item(tercero)
        with pytest.raises(LimiteComentarios):
            publicar_comentario(sesion, db, config_rapida, tercero, "LINK", contador)  # type: ignore[arg-type]
        assert len(cliente.comentarios) == 2


def test_accion_bloqueada_detiene_la_corrida(tmp_path: Path, config_rapida: Config) -> None:
    cliente = ClienteComentarios(excepcion=RuntimeError("feedback_required"))
    sesion = SesionFalsa(cliente)
    with Database(tmp_path / "t.db") as db:
        item = _item()
        db.upsert_item(item)
        with pytest.raises(ActionBlocked):
            publicar_comentario(
                sesion,  # type: ignore[arg-type]
                db,
                config_rapida,
                item,
                "LINK",
                ContadorComentarios(5),
            )
        # El intento fallido queda registrado, pero sin marca de comentado
        guardado = db.get_comment_action(item.shortcode)
        assert guardado.estado == "blocked"
        assert not db.already_commented(item.shortcode)


# --- pendientes de DM ----------------------------------------------------


def test_lista_los_pendientes_de_dm(tmp_path: Path) -> None:
    with Database(tmp_path / "t.db") as db:
        for shortcode, estado in (("A", "received"), ("B", "timeout"), ("C", "commented")):
            item = _item(shortcode)
            item.status = ItemStatus.ANALYZED
            db.upsert_item(item)
            db.save_comment_action(
                shortcode,
                DmResult(estado=estado, keyword="LINK", commented_at=utcnow_iso()),
            )
        # Uno que nunca se comento: no debe aparecer
        db.upsert_item(_item("D"))

        pendientes = {i.shortcode for i in db.pendientes_de_dm()}
        assert pendientes == {"B", "C"}
