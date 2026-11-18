"""Lo que el usuario ya tiene en sus proyectos no deberia recomendarsele."""

from __future__ import annotations

import json
from pathlib import Path

from instapull.catalog import canonicalizar, escanear
from instapull.db import Database
from instapull.models import Analysis, Categoria, ItemStatus, MediaType, SavedItem


def _proyecto(raiz: Path, nombre: str) -> Path:
    p = raiz / nombre
    (p / ".claude" / "skills").mkdir(parents=True)
    return p


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


def _analisis(herramientas: list[str]) -> Analysis:
    return Analysis(
        titulo="Post demo",
        resumen="Resumen.",
        categoria=Categoria.HERRAMIENTA_IA,
        herramientas=herramientas,
        valoracion=4,
        modelo="modelo/prueba",
    )


# --- escaneo del disco ------------------------------------------------


def test_encuentra_skills_mcps_y_dependencias(tmp_path: Path) -> None:
    proyecto = _proyecto(tmp_path, "MiApp")
    (proyecto / ".claude" / "skills" / "add-login").mkdir()
    (proyecto / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "supabase": {
                        "command": "npx",
                        "args": ["-y", "@supabase/mcp-server-supabase@latest"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (proyecto / "package.json").write_text(
        json.dumps({"dependencies": {"zustand": "^5"}}), encoding="utf-8"
    )

    claves = {h["clave"] for h in escanear([tmp_path])}
    assert canonicalizar("Supabase") in claves
    assert canonicalizar("zustand") in claves
    assert canonicalizar("add login") in claves


def test_las_dependencias_se_pueden_apagar(tmp_path: Path) -> None:
    proyecto = _proyecto(tmp_path, "MiApp")
    (proyecto / "package.json").write_text(
        json.dumps({"dependencies": {"zustand": "^5"}}), encoding="utf-8"
    )
    assert escanear([tmp_path], incluir_dependencias=False) == []


def test_un_package_json_roto_no_tumba_el_escaneo(tmp_path: Path) -> None:
    proyecto = _proyecto(tmp_path, "MiApp")
    (proyecto / "package.json").write_text("{ esto no es json", encoding="utf-8")
    (proyecto / ".claude" / "skills" / "supabase").mkdir()

    claves = {h["clave"] for h in escanear([tmp_path])}
    assert canonicalizar("supabase") in claves


def test_node_modules_no_se_toma_como_proyecto(tmp_path: Path) -> None:
    modulo = tmp_path / "node_modules" / "cualquiera"
    modulo.mkdir(parents=True)
    (tmp_path / "node_modules" / "package.json").write_text(
        json.dumps({"dependencies": {"lodash": "^4"}}), encoding="utf-8"
    )
    assert escanear([tmp_path]) == []


def test_los_repos_clonados_van_por_su_propia_raiz(tmp_path: Path) -> None:
    (tmp_path / "github" / "context7").mkdir(parents=True)
    # Como raiz de proyectos no aporta nada; como raiz de repos, si
    assert escanear([], raices_repos=[tmp_path])[0]["clave"] == canonicalizar("context7")


# --- cruce con el catalogo -------------------------------------------


def test_el_catalogo_marca_lo_que_ya_tengo(tmp_path: Path) -> None:
    proyecto = _proyecto(tmp_path / "proyectos", "MiApp")
    (proyecto / ".claude" / "skills" / "supabase").mkdir()

    with Database(tmp_path / "test.db") as db:
        db.upsert_item(_item("AAA"))
        db.registrar_herramientas("AAA", _analisis(["Supabase", "Runway"]))

        unicas, coinciden = db.registrar_inventario(escanear([tmp_path / "proyectos"]))
        assert unicas >= 1 and coinciden == 1

        por_nombre = {f["nombre"]: f for f in db.catalogo()}
        assert por_nombre["Supabase"]["ya_tengo"] is True
        assert por_nombre["Supabase"]["fuente_propia"] == "skill"
        assert por_nombre["Supabase"]["donde_la_tengo"] == ["MiApp"]
        assert por_nombre["Runway"]["ya_tengo"] is False


def test_reescanear_olvida_lo_que_ya_no_esta(tmp_path: Path) -> None:
    proyectos = tmp_path / "proyectos"
    proyecto = _proyecto(proyectos, "MiApp")
    skill = proyecto / ".claude" / "skills" / "supabase"
    skill.mkdir()

    with Database(tmp_path / "test.db") as db:
        db.upsert_item(_item("AAA"))
        db.registrar_herramientas("AAA", _analisis(["Supabase"]))
        db.registrar_inventario(escanear([proyectos]))
        assert db.catalogo()[0]["ya_tengo"] is True

        # El usuario borra la skill: deja de estar "ya la tengo"
        skill.rmdir()
        db.registrar_inventario(escanear([proyectos]))
        assert db.catalogo()[0]["ya_tengo"] is False
