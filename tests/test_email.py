"""Resumen diario por correo: render, envio con Resend y no repetir elementos."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import respx

from instapull.config import EmailConfig
from instapull.db import Database
from instapull.models import (
    Analysis,
    Categoria,
    DmResult,
    ItemStatus,
    MediaType,
    ProcessedItem,
    ResolvedLink,
    SavedItem,
)
from instapull.notifications import DigestResult, EmailNotifier, debe_enviar_ahora
from instapull.notifications.render import asunto_digest, render_html, render_texto

FECHA = "2026-08-19"


def _procesado(
    shortcode: str = "AAA1",
    titulo: str = "Herramienta demo",
    valoracion: int = 4,
    categoria: Categoria = Categoria.HERRAMIENTA_IA,
) -> ProcessedItem:
    return ProcessedItem(
        item=SavedItem(
            shortcode=shortcode,
            author="cuenta_demo",
            taken_at="2026-08-18T10:22:00+00:00",
            permalink=f"https://www.instagram.com/p/{shortcode}/",
            media_type=MediaType.VIDEO,
            status=ItemStatus.ANALYZED,
        ),
        analysis=Analysis(
            titulo=titulo,
            resumen="Genera videos con IA en un clic.",
            categoria=categoria,
            herramientas=["Demo"],
            valoracion=valoracion,
            etiquetas=["video"],
        ),
    )


def _config(**cambios: object) -> EmailConfig:
    base: dict[str, object] = {
        "enabled": True,
        "provider": "resend",
        "from_address": "InstaPull <avisos@ejemplo.test>",
        "to_address": "yo@ejemplo.test",
    }
    base.update(cambios)
    return EmailConfig(**base)  # type: ignore[arg-type]


# --- render ------------------------------------------------------------


def test_el_html_incluye_el_contenido_del_elemento() -> None:
    html = render_html([_procesado()], FECHA)
    assert "Herramienta demo" in html
    assert "Genera videos con IA" in html
    assert "https://www.instagram.com/p/AAA1/" in html
    assert Categoria.HERRAMIENTA_IA.value in html


def test_el_html_escapa_lo_que_viene_del_post() -> None:
    """Un caption con HTML no debe poder inyectar marcado en el correo."""
    procesado = _procesado(titulo="<script>alert('x')</script>")
    html = render_html([procesado], FECHA)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_marca_los_enlaces_que_llegaron_por_dm() -> None:
    procesado = _procesado()
    procesado.links = [
        ResolvedLink(
            url_original="https://bit.ly/abc",
            url_final="https://github.com/org/repo",
            titulo="org/repo",
            tipo="github_repo",
        )
    ]
    procesado.dm = DmResult(estado="received", dm_links=["https://github.com/org/repo"])

    assert "(via DM)" in render_html([procesado], FECHA)
    assert "(via DM)" in render_texto([procesado], FECHA)


def test_el_texto_plano_lista_los_elementos() -> None:
    texto = render_texto([_procesado(), _procesado("BBB2", "Otra cosa")], FECHA)
    assert "Herramienta demo" in texto
    assert "Otra cosa" in texto
    assert "<div" not in texto


def test_asunto_singular_y_plural() -> None:
    assert (
        asunto_digest([_procesado()], FECHA) == "InstaPull 2026-08-19: 1 elemento nuevo"
    )
    assert "2 elementos nuevos" in asunto_digest(
        [_procesado(), _procesado("BBB2")], FECHA
    )


# --- envio -------------------------------------------------------------


@respx.mock
def test_envia_y_devuelve_el_id_del_mensaje() -> None:
    ruta = respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(200, json={"id": "msg_123"})
    )

    resultado = EmailNotifier(_config(), api_key="re_test").send_daily_digest(
        [_procesado()], fecha=FECHA
    )

    assert resultado.estado == "sent"
    assert resultado.enviado
    assert resultado.message_id == "msg_123"
    assert resultado.shortcodes == ["AAA1"]

    enviado = ruta.calls.last.request
    assert enviado.headers["authorization"] == "Bearer re_test"

    cuerpo = json.loads(enviado.content)
    assert cuerpo["to"] == ["yo@ejemplo.test"]
    assert cuerpo["subject"] == "InstaPull 2026-08-19: 1 elemento nuevo"
    assert "Herramienta demo" in cuerpo["html"]
    assert "Herramienta demo" in cuerpo["text"]


@respx.mock
def test_apagado_no_manda_nada() -> None:
    ruta = respx.post("https://api.resend.com/emails")
    resultado = EmailNotifier(
        _config(enabled=False), api_key="re_test"
    ).send_daily_digest([_procesado()], fecha=FECHA)
    assert resultado.estado == "disabled"
    assert not ruta.called


@respx.mock
def test_sin_elementos_no_manda_nada() -> None:
    ruta = respx.post("https://api.resend.com/emails")
    resultado = EmailNotifier(_config(), api_key="re_test").send_daily_digest(
        [], fecha=FECHA
    )
    assert resultado.estado == "sin_novedades"
    assert not ruta.called


@respx.mock
def test_sin_clave_avisa_y_no_llama_a_la_api() -> None:
    ruta = respx.post("https://api.resend.com/emails")
    resultado = EmailNotifier(_config(), api_key="").send_daily_digest(
        [_procesado()], fecha=FECHA
    )
    assert resultado.estado == "error"
    assert "RESEND_API_KEY" in (resultado.error or "")
    assert not ruta.called


@respx.mock
def test_dry_run_arma_el_correo_pero_no_lo_manda() -> None:
    ruta = respx.post("https://api.resend.com/emails")
    resultado = EmailNotifier(_config(), api_key="re_test").send_daily_digest(
        [_procesado()], fecha=FECHA, dry_run=True
    )
    assert resultado.estado == "dry_run"
    assert resultado.asunto
    assert not ruta.called


@respx.mock
def test_dry_run_sin_clave_muestra_el_plan_y_avisa() -> None:
    """Se puede ver que saldria antes de terminar de configurar el correo."""
    ruta = respx.post("https://api.resend.com/emails")
    resultado = EmailNotifier(_config(), api_key="").send_daily_digest(
        [_procesado()], fecha=FECHA, dry_run=True
    )
    assert resultado.estado == "dry_run"
    assert resultado.shortcodes == ["AAA1"]
    assert "RESEND_API_KEY" in resultado.detalle
    assert not ruta.called


@respx.mock
def test_un_rechazo_de_resend_no_lanza_excepcion() -> None:
    respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(422, text='{"message":"dominio no verificado"}')
    )
    resultado = EmailNotifier(_config(), api_key="re_test").send_daily_digest(
        [_procesado()], fecha=FECHA
    )
    assert resultado.estado == "error"
    assert "422" in (resultado.error or "")


@respx.mock
def test_un_fallo_de_red_no_lanza_excepcion() -> None:
    respx.post("https://api.resend.com/emails").mock(
        side_effect=httpx.ConnectError("sin conexion")
    )
    resultado = EmailNotifier(_config(), api_key="re_test").send_daily_digest(
        [_procesado()], fecha=FECHA
    )
    assert resultado.estado == "error"
    assert not resultado.enviado


@respx.mock
def test_respeta_el_tope_y_manda_primero_lo_mejor_valorado() -> None:
    respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(200, json={"id": "msg_1"})
    )
    items = [
        _procesado("BAJO", valoracion=2),
        _procesado("ALTO", valoracion=5),
        _procesado("MEDIO", valoracion=3),
    ]

    resultado = EmailNotifier(
        _config(max_items=2), api_key="re_test"
    ).send_daily_digest(items, fecha=FECHA)

    assert resultado.shortcodes == ["ALTO", "MEDIO"]
    assert "quedan 1" in resultado.detalle


def test_un_proveedor_no_soportado_se_rechaza() -> None:
    resultado = EmailNotifier(
        _config(provider="mailgun"), api_key="clave"
    ).send_daily_digest([_procesado()], fecha=FECHA)
    assert resultado.estado == "error"
    assert "mailgun" in (resultado.error or "")


# --- cuando toca enviar ------------------------------------------------


def _momento(hora: int, dia: int = 19) -> datetime:
    return datetime(2026, 8, dia, hora, 0, tzinfo=timezone.utc)


def test_no_envia_antes_de_la_hora_configurada() -> None:
    toca, motivo = debe_enviar_ahora(_config(send_hour=9), None, _momento(7))
    assert not toca
    assert "9:00" in motivo


def test_no_envia_dos_veces_el_mismo_dia() -> None:
    toca, motivo = debe_enviar_ahora(
        _config(send_hour=9), "2026-08-19T09:30:00+00:00", _momento(14)
    )
    assert not toca
    assert "ya se envio hoy" in motivo


def test_envia_si_el_ultimo_fue_ayer() -> None:
    toca, _ = debe_enviar_ahora(
        _config(send_hour=9), "2026-08-18T09:30:00+00:00", _momento(10)
    )
    assert toca


def test_envia_la_primera_vez() -> None:
    toca, _ = debe_enviar_ahora(_config(send_hour=9), None, _momento(10))
    assert toca


# --- persistencia del digest -------------------------------------------


def _guardar(db: Database, procesado: ProcessedItem) -> None:
    db.upsert_item(procesado.item)
    assert procesado.analysis is not None
    db.save_analysis(procesado.item.shortcode, procesado.analysis)


def test_un_elemento_notificado_no_vuelve_a_salir(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        _guardar(db, _procesado("AAA1"))
        _guardar(db, _procesado("BBB2"))
        assert len(db.pendientes_de_email()) == 2

        db.registrar_digest(["AAA1"], asunto="asunto", estado="sent", message_id="m1")

        pendientes = db.pendientes_de_email()
        assert [p.item.shortcode for p in pendientes] == ["BBB2"]
        assert db.stats()["digests_enviados"] == 1
        assert db.stats()["notificados_por_email"] == 1


def test_si_el_envio_fallo_los_elementos_siguen_pendientes(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        _guardar(db, _procesado("AAA1"))
        db.registrar_digest(
            ["AAA1"], asunto="asunto", estado="error", error="Resend respondio 422"
        )

        assert [p.item.shortcode for p in db.pendientes_de_email()] == ["AAA1"]
        assert db.stats()["digests_enviados"] == 0
        assert db.ultimo_digest() is None


def test_el_ultimo_digest_es_el_mas_reciente_enviado(tmp_path: Path) -> None:
    with Database(tmp_path / "test.db") as db:
        _guardar(db, _procesado("AAA1"))
        _guardar(db, _procesado("BBB2"))
        db.registrar_digest(["AAA1"], asunto="primero", estado="sent")
        db.registrar_digest(["BBB2"], asunto="segundo", estado="sent")

        ultimo = db.ultimo_digest()
        assert ultimo is not None
        assert ultimo["asunto"] == "segundo"
        assert ultimo["sent_at"]


def test_el_resultado_serializa_como_modelo() -> None:
    """DigestResult es pydantic: el CLI y los logs lo usan como dict."""
    datos = DigestResult(estado="sent", asunto="x").model_dump()
    assert datos["estado"] == "sent"
    assert datos["shortcodes"] == []
