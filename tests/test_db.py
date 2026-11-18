"""Persistencia e idempotencia."""

from __future__ import annotations

from pathlib import Path

from instapull.db import Database
from instapull.models import (
    Analysis,
    Categoria,
    DmResult,
    ItemStatus,
    MediaType,
    ResolvedLink,
    SavedItem,
    utcnow_iso,
)


def _item(shortcode: str = "TEST001") -> SavedItem:
    return SavedItem(
        shortcode=shortcode,
        media_id="123456",
        author="cuenta_demo",
        taken_at="2026-03-14T10:22:00+00:00",
        caption="Comenta LINK",
        permalink=f"https://www.instagram.com/p/{shortcode}/",
        media_type=MediaType.VIDEO,
    )


def _analisis() -> Analysis:
    return Analysis(
        titulo="Herramienta demo",
        resumen="Resumen de prueba.",
        categoria=Categoria.HERRAMIENTA_IA,
        herramientas=["Demo"],
        valoracion=4,
        etiquetas=["prueba"],
        modelo="modelo/prueba",
    )


def test_upsert_no_duplica(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        db.upsert_item(_item())
        db.upsert_item(_item())
        assert db.stats()["elementos"] == 1


def test_incremental_saltea_lo_analizado(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        item = _item()
        db.upsert_item(item)
        assert not db.is_analyzed(item.shortcode)

        item.status = ItemStatus.ANALYZED
        db.upsert_item(item)
        assert db.is_analyzed(item.shortcode)


def test_nunca_comenta_dos_veces(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        item = _item()
        db.upsert_item(item)
        assert not db.already_commented(item.shortcode)

        dm = DmResult(
            estado="commented",
            keyword="LINK",
            comment_id="99",
            commented_at=utcnow_iso(),
        )
        db.save_comment_action(item.shortcode, dm)
        assert db.already_commented(item.shortcode)

        # Una segunda escritura (al recibir el DM) no crea otra fila ni borra la
        # marca de que ya se comento.
        db.save_comment_action(
            item.shortcode,
            DmResult(estado="received", keyword="LINK", dm_links=["https://x.test"]),
        )
        assert db.stats()["comentados"] == 1
        guardado = db.get_comment_action(item.shortcode)
        assert guardado.estado == "received"
        assert guardado.commented_at is not None
        assert guardado.dm_links == ["https://x.test"]


def test_guarda_y_recupera_el_analisis(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        item = _item()
        item.status = ItemStatus.ANALYZED
        db.upsert_item(item)
        db.save_analysis(item.shortcode, _analisis(), transcript="hola", ocr_text="OCR")

        procesados = db.fetch_processed()
        assert len(procesados) == 1
        recuperado = procesados[0]
        assert recuperado.analysis is not None
        assert recuperado.analysis.categoria is Categoria.HERRAMIENTA_IA
        assert recuperado.analysis.valoracion == 4
        assert recuperado.analysis.herramientas == ["Demo"]


def test_los_enlaces_no_se_duplican(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        item = _item()
        db.upsert_item(item)
        link = ResolvedLink(
            url_original="https://bit.ly/abc",
            url_final="https://github.com/org/repo",
            tipo="github_repo",
        )
        db.save_links(item.shortcode, [link, link])
        db.save_links(item.shortcode, [link])
        assert len(db.get_links(item.shortcode)) == 1


def test_ordena_por_valoracion(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        for shortcode, valoracion in (("A", 2), ("B", 5), ("C", 3)):
            item = _item(shortcode)
            item.status = ItemStatus.ANALYZED
            db.upsert_item(item)
            analisis = _analisis()
            analisis.valoracion = valoracion
            db.save_analysis(shortcode, analisis)

        valoraciones = [p.analysis.valoracion for p in db.fetch_processed()]  # type: ignore[union-attr]
        assert valoraciones == [5, 3, 2]


def test_registra_las_corridas(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        run_id = db.start_run("prueba")
        db.finish_run(run_id, procesados=3, errores=1, comentarios=2)
        assert db.stats()["corridas"] == 1
