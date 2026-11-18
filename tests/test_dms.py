"""Lectura de DMs: bandeja normal, solicitudes de mensaje y recuperacion tardia."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from instapull.config import CommentsConfig
from instapull.instagram.dms import (
    _botones_cta,
    _mensaje_a_texto,
    _ts_utc,
    buscar_hilo,
    esperar_dm,
    revisar_dm_una_vez,
)
from instapull.links.resolver import extraer_urls
from instapull.models import DmResult, SavedItem


class MensajeFalso:
    """Imita un DirectMessage de instagrapi (expone model_dump)."""

    def __init__(
        self,
        id_: str,
        user_id: str,
        datos: dict,
        timestamp: datetime | None = None,
    ) -> None:
        self.id = id_
        self.user_id = user_id
        self._datos = datos
        self.timestamp = timestamp

    def model_dump(self) -> dict:
        return self._datos


def _boton(titulo: str, texto: str = "Mira esto") -> dict:
    """Payload real de un template con boton (raw_xma.generic_xma[].cta_buttons)."""
    return {
        "item_type": "generic_xma",
        "raw_xma": {
            "generic_xma": [
                {
                    "title_text": texto,
                    "cta_buttons": [
                        {
                            "title": titulo,
                            "action_url": "",
                            "cta_type": "postback",
                            "platform_token": {
                                "postback": {"postback_payload": "1:GT-PB:ACT::abc"}
                            },
                        }
                    ],
                }
            ]
        },
    }


class UsuarioFalso:
    def __init__(self, pk: str) -> None:
        self.pk = pk


class HiloPendienteFalso:
    def __init__(self, id_: str, users: list[UsuarioFalso]) -> None:
        self.id = id_
        self.users = users


class ClienteFalso:
    """Cliente de Instagram simulado, configurable por escenario."""

    def __init__(
        self,
        hilo_normal: dict | None = None,
        pendientes: list[HiloPendienteFalso] | None = None,
        mensajes: list[MensajeFalso] | None = None,
    ) -> None:
        self.user_id = "999"
        self._hilo_normal = hilo_normal
        self._pendientes = pendientes or []
        self._mensajes = mensajes or []
        self.aprobados: list[int] = []
        self.enviados: list[tuple[str, list[str]]] = []
        self.seguidos: list[int] = []

    def user_follow(self, user_id: int) -> bool:
        self.seguidos.append(user_id)
        return True

    def user_id_from_username(self, _username: str) -> str:
        return "555"

    def direct_thread_by_participants(self, _user_ids: list[int]) -> dict:
        if self._hilo_normal is None:
            raise RuntimeError("no existe hilo")
        return self._hilo_normal

    def direct_pending_inbox(self, amount: int = 20) -> list[HiloPendienteFalso]:
        return self._pendientes

    def direct_pending_approve(self, thread_id: int) -> bool:
        self.aprobados.append(thread_id)
        return True

    def direct_messages(self, _thread_id: str, amount: int = 20) -> list[MensajeFalso]:
        # instagrapi devuelve del mas nuevo al mas viejo
        return list(reversed(self._mensajes))

    def direct_send(self, text: str, thread_ids: list[str]) -> None:
        self.enviados.append((text, thread_ids))


class SesionFalsa:
    def __init__(self, cliente: ClienteFalso) -> None:
        self.client = cliente


def _item() -> SavedItem:
    return SavedItem(shortcode="TEST001", author="cuenta_demo", media_id="1")


class ConfigFalsa:
    """Solo lo que `esperar_dm` consulta de Config."""

    def __init__(self, comments: CommentsConfig) -> None:
        self.comments = comments


def _config_comentarios(auto_follow: bool = False, ventana: int = 1) -> ConfigFalsa:
    # Ventana corta: alcanza para las pasadas del test y lo mantiene rapido.
    return ConfigFalsa(
        CommentsConfig(
            enabled=True,
            dm_wait_max_seconds=ventana,
            dm_poll_intervals=[1],
            auto_follow=auto_follow,
        )
    )


def test_encuentra_el_hilo_en_la_bandeja_normal() -> None:
    cliente = ClienteFalso(hilo_normal={"thread_id": "111"})
    resultado = buscar_hilo(SesionFalsa(cliente), "cuenta_demo")  # type: ignore[arg-type]
    assert resultado == ("111", "555")
    assert cliente.aprobados == []


def test_encuentra_el_hilo_en_solicitudes_y_lo_aprueba() -> None:
    """Si la cuenta no te sigue, su DM cae en 'solicitudes de mensaje'."""
    cliente = ClienteFalso(
        hilo_normal=None,
        pendientes=[HiloPendienteFalso("222", [UsuarioFalso("555")])],
    )
    resultado = buscar_hilo(SesionFalsa(cliente), "cuenta_demo")  # type: ignore[arg-type]
    assert resultado == ("222", "555")
    assert cliente.aprobados == [222]


def test_sin_hilo_en_ningun_lado() -> None:
    cliente = ClienteFalso(hilo_normal=None, pendientes=[])
    assert buscar_hilo(SesionFalsa(cliente), "cuenta_demo") is None  # type: ignore[arg-type]


def test_ignora_solicitudes_de_otras_cuentas() -> None:
    cliente = ClienteFalso(
        hilo_normal=None,
        pendientes=[HiloPendienteFalso("333", [UsuarioFalso("777")])],
    )
    assert buscar_hilo(SesionFalsa(cliente), "cuenta_demo") is None  # type: ignore[arg-type]


def test_aplana_el_mensaje_y_encuentra_el_enlace_anidado() -> None:
    """El enlace suele venir en link_context, no en el texto plano."""
    mensaje = MensajeFalso(
        "m1",
        "555",
        {
            "id": "m1",
            "text": "Aca tenes lo que pediste",
            "link": {
                "text": "mira esto",
                "link_context": {"link_url": "https://ejemplo.test/repo"},
            },
        },
    )
    texto = _mensaje_a_texto(mensaje)
    assert "https://ejemplo.test/repo" in texto
    assert extraer_urls(texto) == ["https://ejemplo.test/repo"]


def test_recupera_un_dm_tardio() -> None:
    cliente = ClienteFalso(
        hilo_normal={"thread_id": "111"},
        mensajes=[MensajeFalso("m1", "555", {"text": "Listo: https://ejemplo.test/repo"})],
    )
    dm = DmResult(
        estado="timeout", keyword="LINK", commented_at="2026-03-14T10:00:00+00:00"
    )
    resultado = revisar_dm_una_vez(SesionFalsa(cliente), _item(), dm, extraer_urls)  # type: ignore[arg-type]
    assert resultado.estado == "received"
    assert resultado.dm_links == ["https://ejemplo.test/repo"]
    assert resultado.dm_received_at is not None


def test_no_marca_recibido_si_el_dm_no_trae_enlace() -> None:
    cliente = ClienteFalso(
        hilo_normal={"thread_id": "111"},
        mensajes=[MensajeFalso("m1", "555", {"text": "Hola! Gracias por comentar"})],
    )
    dm = DmResult(estado="timeout", keyword="LINK")
    resultado = revisar_dm_una_vez(SesionFalsa(cliente), _item(), dm, extraer_urls)  # type: ignore[arg-type]
    assert resultado.estado == "timeout"
    assert resultado.dm_links == []


def test_ignora_los_mensajes_propios() -> None:
    """Un mensaje enviado por mi cuenta no cuenta como respuesta del bot."""
    cliente = ClienteFalso(
        hilo_normal={"thread_id": "111"},
        mensajes=[MensajeFalso("m1", "999", {"text": "https://ejemplo.test/mio"})],
    )
    dm = DmResult(estado="timeout")
    resultado = revisar_dm_una_vez(SesionFalsa(cliente), _item(), dm, extraer_urls)  # type: ignore[arg-type]
    assert resultado.estado == "timeout"
    assert resultado.dm_links == []


# --- Correlacion por timestamp -------------------------------------------------
# El hilo de DM es por AUTOR, no por post. Si el mismo autor tiene varios posts
# en la coleccion, la respuesta de un post viejo no debe atribuirse al comentario
# recien publicado.


def test_descarta_la_respuesta_anterior_al_comentario() -> None:
    """Un DM previo al comentario es de otro post del mismo autor, no de este."""
    comentado = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
    viejo = MensajeFalso(
        "m1",
        "555",
        {"text": "Guia anterior: https://ejemplo.test/otro-post"},
        timestamp=comentado - timedelta(minutes=20),
    )
    cliente = ClienteFalso(hilo_normal={"thread_id": "111"}, mensajes=[viejo])
    dm = DmResult(estado="timeout", commented_at=comentado.isoformat())

    resultado = revisar_dm_una_vez(SesionFalsa(cliente), _item(), dm, extraer_urls)  # type: ignore[arg-type]

    assert resultado.estado == "timeout"
    assert resultado.dm_links == []


def test_acepta_la_respuesta_posterior_al_comentario() -> None:
    comentado = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
    nuevo = MensajeFalso(
        "m2",
        "555",
        {"text": "Aca va: https://ejemplo.test/este-post"},
        timestamp=comentado + timedelta(seconds=7),
    )
    cliente = ClienteFalso(hilo_normal={"thread_id": "111"}, mensajes=[nuevo])
    dm = DmResult(estado="timeout", commented_at=comentado.isoformat())

    resultado = revisar_dm_una_vez(SesionFalsa(cliente), _item(), dm, extraer_urls)  # type: ignore[arg-type]

    assert resultado.estado == "received"
    assert resultado.dm_links == ["https://ejemplo.test/este-post"]


def test_un_mensaje_sin_timestamp_no_se_pierde() -> None:
    """Ante la duda se procesa: perder el enlace es peor que un falso positivo."""
    cliente = ClienteFalso(
        hilo_normal={"thread_id": "111"},
        mensajes=[MensajeFalso("m1", "555", {"text": "https://ejemplo.test/x"})],
    )
    dm = DmResult(estado="timeout", commented_at="2026-03-14T10:00:00+00:00")
    resultado = revisar_dm_una_vez(SesionFalsa(cliente), _item(), dm, extraer_urls)  # type: ignore[arg-type]
    assert resultado.estado == "received"


def test_timestamp_naive_se_interpreta_como_hora_local() -> None:
    """instagrapi entrega naive en hora local; compararlo como UTC lo corre."""
    naive = datetime(2026, 3, 14, 4, 0)
    esperado = naive.astimezone().astimezone(timezone.utc)
    assert _ts_utc(MensajeFalso("m1", "555", {}, timestamp=naive)) == esperado


# --- Botones del template ------------------------------------------------------


def test_extrae_la_etiqueta_del_boton() -> None:
    mensaje = MensajeFalso("m1", "555", _boton("Send me the guide"))
    assert _botones_cta(mensaje) == [
        {"titulo": "Send me the guide", "tipo": "postback"}
    ]


def test_mensaje_sin_boton_no_devuelve_nada() -> None:
    assert _botones_cta(MensajeFalso("m1", "555", {"text": "hola"})) == []


def test_responde_con_la_etiqueta_literal_del_boton() -> None:
    """instagrapi no sabe pulsar un postback; el texto del boton si dispara al bot."""
    comentado = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
    mensaje = MensajeFalso(
        "m1",
        "555",
        _boton("Send me the guide", "Tap 'send me the guide' y te lo mando"),
        timestamp=comentado + timedelta(seconds=5),
    )
    cliente = ClienteFalso(hilo_normal={"thread_id": "111"}, mensajes=[mensaje])
    dm = DmResult(estado="commented", commented_at=comentado.isoformat())
    config = _config_comentarios()

    resultado = esperar_dm(
        SesionFalsa(cliente),  # type: ignore[arg-type]
        config,  # type: ignore[arg-type]
        _item(),
        dm,
        extraer_urls,
        responder=lambda _texto: "respuesta inventada por la IA",
    )

    assert cliente.enviados == [("Send me the guide", ["111"])]
    assert resultado.turnos == 1


# --- Auto-follow ---------------------------------------------------------------
# Accion PUBLICA: solo si `auto_follow` esta activo y el bot lo exige.


def _mensaje_pide_follow(comentado: datetime) -> MensajeFalso:
    return MensajeFalso(
        "m1",
        "555",
        _boton("Yes, that's me", "Please confirm you are following! (or it won't work)"),
        timestamp=comentado + timedelta(seconds=3),
    )


def test_sigue_al_autor_si_el_bot_lo_exige() -> None:
    comentado = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
    cliente = ClienteFalso(
        hilo_normal={"thread_id": "111"}, mensajes=[_mensaje_pide_follow(comentado)]
    )
    dm = DmResult(estado="commented", commented_at=comentado.isoformat())

    esperar_dm(
        SesionFalsa(cliente),  # type: ignore[arg-type]
        _config_comentarios(auto_follow=True, ventana=3),  # type: ignore[arg-type]
        _item(),
        dm,
        extraer_urls,
    )

    assert cliente.seguidos == [555]


def test_no_sigue_a_nadie_si_el_flag_esta_apagado() -> None:
    """Sin `auto_follow` no se toca la cuenta, aunque el bot lo pida."""
    comentado = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
    cliente = ClienteFalso(
        hilo_normal={"thread_id": "111"}, mensajes=[_mensaje_pide_follow(comentado)]
    )
    dm = DmResult(estado="commented", commented_at=comentado.isoformat())

    esperar_dm(
        SesionFalsa(cliente),  # type: ignore[arg-type]
        _config_comentarios(auto_follow=False),  # type: ignore[arg-type]
        _item(),
        dm,
        extraer_urls,
    )

    assert cliente.seguidos == []


def test_no_sigue_si_el_bot_no_lo_pide() -> None:
    """Un DM normal con boton no justifica seguir a nadie."""
    comentado = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
    mensaje = MensajeFalso(
        "m1",
        "555",
        _boton("Send me the guide", "Tap el boton y te lo mando"),
        timestamp=comentado + timedelta(seconds=3),
    )
    cliente = ClienteFalso(hilo_normal={"thread_id": "111"}, mensajes=[mensaje])
    dm = DmResult(estado="commented", commented_at=comentado.isoformat())

    esperar_dm(
        SesionFalsa(cliente),  # type: ignore[arg-type]
        _config_comentarios(auto_follow=True),  # type: ignore[arg-type]
        _item(),
        dm,
        extraer_urls,
    )

    assert cliente.seguidos == []
    assert cliente.enviados == [("Send me the guide", ["111"])]


def test_sigue_una_sola_vez_por_espera() -> None:
    comentado = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
    mensajes = [
        MensajeFalso(
            f"m{n}",
            "555",
            {"text": "Make sure you follow me first!"},
            timestamp=comentado + timedelta(seconds=n),
        )
        for n in (1, 2, 3)
    ]
    cliente = ClienteFalso(hilo_normal={"thread_id": "111"}, mensajes=mensajes)
    dm = DmResult(estado="commented", commented_at=comentado.isoformat())

    esperar_dm(
        SesionFalsa(cliente),  # type: ignore[arg-type]
        _config_comentarios(auto_follow=True, ventana=4),  # type: ignore[arg-type]
        _item(),
        dm,
        extraer_urls,
    )

    assert cliente.seguidos == [555]


def test_sin_boton_responde_con_la_ia() -> None:
    comentado = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
    mensaje = MensajeFalso(
        "m1",
        "555",
        {"text": "Responde SI para recibirlo"},
        timestamp=comentado + timedelta(seconds=5),
    )
    cliente = ClienteFalso(hilo_normal={"thread_id": "111"}, mensajes=[mensaje])
    dm = DmResult(estado="commented", commented_at=comentado.isoformat())

    esperar_dm(
        SesionFalsa(cliente),  # type: ignore[arg-type]
        _config_comentarios(),  # type: ignore[arg-type]
        _item(),
        dm,
        extraer_urls,
        responder=lambda _texto: "SI",
    )

    assert cliente.enviados == [("SI", ["111"])]
