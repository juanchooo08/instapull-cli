"""Catalogo global: una herramienta, una fila, aunque el modelo la escriba mal."""

from __future__ import annotations

from pathlib import Path

from instapull.catalog import canonicalizar, render_catalogo
from instapull.db import Database
from instapull.models import (
    Analysis,
    Categoria,
    ItemStatus,
    MediaType,
    ResolvedLink,
    SavedItem,
)


def _item(shortcode: str) -> SavedItem:
    return SavedItem(
        shortcode=shortcode,
        media_id="123456",
        author="cuenta_demo",
        taken_at="2026-03-14T10:22:00+00:00",
        caption="Comenta LINK",
        permalink=f"https://www.instagram.com/p/{shortcode}/",
        media_type=MediaType.VIDEO,
        status=ItemStatus.ANALYZED,
    )


def _analisis(herramientas: list[str], valoracion: int = 4) -> Analysis:
    return Analysis(
        titulo="Post demo",
        resumen="Resumen.",
        categoria=Categoria.HERRAMIENTA_IA,
        herramientas=herramientas,
        valoracion=valoracion,
        modelo="modelo/prueba",
    )


# --- clave canonica ---------------------------------------------------


def test_las_variantes_del_mismo_nombre_colapsan() -> None:
    esperada = canonicalizar("ElevenLabs")
    for variante in ("Eleven Labs", "elevenlabs.io", "ElevenLabs (voz)", "eleven-labs"):
        assert canonicalizar(variante) == esperada


def test_una_url_se_reduce_a_su_dominio() -> None:
    assert canonicalizar("https://n8n.io/workflows") == canonicalizar("n8n")


def test_las_palabras_genericas_no_son_herramientas() -> None:
    for basura in ("IA", "herramientas", "n/a", "  ", "prompt"):
        assert canonicalizar(basura) == ""


def test_nombres_distintos_no_se_mezclan() -> None:
    assert canonicalizar("Claude") != canonicalizar("Claude Code")
    assert canonicalizar("Notion") != canonicalizar("Motion")


# --- deduplicacion en la base ----------------------------------------


def test_la_misma_herramienta_en_dos_posts_es_una_sola_fila(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        db.upsert_item(_item("AAA"))
        db.upsert_item(_item("BBB"))

        nuevas, repetidas = db.registrar_herramientas("AAA", _analisis(["Eleven Labs"]))
        assert nuevas == ["Eleven Labs"] and repetidas == []

        # Otro post la escribe distinto: no debe crear una entrada nueva
        nuevas, repetidas = db.registrar_herramientas(
            "BBB", _analisis(["elevenlabs.io"])
        )
        assert nuevas == [] and repetidas == ["Eleven Labs"]

        filas = db.catalogo()
        assert len(filas) == 1
        assert filas[0]["menciones"] == 2
        assert {p["shortcode"] for p in filas[0]["posts"]} == {"AAA", "BBB"}


def test_reanalizar_el_mismo_post_no_infla_el_contador(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        db.upsert_item(_item("AAA"))
        db.registrar_herramientas("AAA", _analisis(["Cursor"]))
        db.registrar_herramientas("AAA", _analisis(["Cursor"]))

        assert db.catalogo()[0]["menciones"] == 1


def test_se_queda_con_la_mejor_valoracion_y_el_enlace(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        db.upsert_item(_item("AAA"))
        db.upsert_item(_item("BBB"))
        db.registrar_herramientas("AAA", _analisis(["Cursor"], valoracion=2))
        db.registrar_herramientas(
            "BBB",
            _analisis(["Cursor"], valoracion=5),
            [
                ResolvedLink(
                    url_original="https://cursor.com", url_final="https://cursor.com"
                )
            ],
        )

        fila = db.catalogo()[0]
        assert fila["valoracion_max"] == 5
        assert fila["url"] == "https://cursor.com"
        # El nombre de la primera aparicion manda
        assert fila["nombre"] == "Cursor"


def test_las_herramientas_conocidas_se_recuerdan(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        db.upsert_item(_item("AAA"))
        db.registrar_herramientas("AAA", _analisis(["Zapier", "Make"]))
        assert set(db.herramientas_conocidas()) == {
            canonicalizar("Zapier"),
            canonicalizar("Make"),
        }


def test_reconstruir_no_duplica_lo_ya_catalogado(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        db.upsert_item(_item("AAA"))
        db.save_analysis("AAA", _analisis(["Cursor", "cursor.com"]))
        db.registrar_herramientas("AAA", _analisis(["Cursor", "cursor.com"]))

        assert db.reconstruir_catalogo() == 1
        assert len(db.catalogo()) == 1


# --- vista interactiva ------------------------------------------------


def test_la_tabla_se_ve_aunque_no_corra_javascript(tmp_path: Path) -> None:
    # La vista previa de adjuntos de Gmail no ejecuta scripts: si las filas se
    # generaran al vuelo, el catalogo se veria vacio justo donde llega el mail.
    with Database(tmp_path / "test.db") as db:
        db.upsert_item(_item("AAA"))
        db.registrar_herramientas("AAA", _analisis(["Runway"]))
        html = render_catalogo(db.catalogo(), "2026-08-20")

    cuerpo = html.split('<tbody id="cuerpo">', 1)[1].split("</tbody>", 1)[0]
    assert "Runway" in cuerpo
    assert cuerpo.count("<tr>") == 1
    # Y los contadores tampoco pueden depender del script
    assert '<b id="kpi-total">1</b>' in html


def test_el_html_es_autocontenido_y_escapa_los_datos(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        db.upsert_item(_item("AAA"))
        db.registrar_herramientas("AAA", _analisis(["</script><b>x</b>"]))
        html = render_catalogo(db.catalogo(), "2026-08-20")

    assert "<!DOCTYPE html>" in html
    # Sin CDN: nada que cargar por red
    assert "src=" not in html
    assert "</script><b>" not in html  # el nombre no rompe la etiqueta
    assert "2026-08-20" in html
