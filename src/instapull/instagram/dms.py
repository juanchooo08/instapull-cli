"""Espera y lectura de los DMs que dispara el bot del post (tipo ManyChat)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from ..config import Config
from ..logging_setup import get_logger
from ..models import DmResult, SavedItem, utcnow_iso
from .auth import InstagramSession
from .ratelimit import clasificar_error, con_reintentos

log = get_logger(__name__)

# Frases con las que el bot condiciona el envio del recurso a que lo sigas
_PIDE_FOLLOW = (
    "follow me",
    "following",
    "follow my",
    "make sure you follow",
    "you are following",
    "you're following",
    "seguirme",
    "sigueme",
    "sígueme",
    "que me sigas",
    "seguime",
)

# Palabras que suelen indicar que el bot espera una respuesta para seguir
_PIDE_RESPUESTA = (
    "responde",
    "respondeme",
    "contesta",
    "escribi",
    "escribe",
    "reply",
    "answer",
    "yes",
    "si quieres",
    "queres",
    "confirma",
    "toca",
    "presiona",
    "click",
)


def _recolectar_strings(dato: Any, acumulado: list[str], profundidad: int = 0) -> None:
    """Recorre un dict/list anidado juntando todos los strings.

    Los DMs de los bots meten el enlace en lugares distintos segun el tipo de
    mensaje (texto plano, link preview, xma_share, generic template), asi que
    se barre la estructura entera en vez de adivinar el campo.
    """
    if profundidad > 6:
        return
    if isinstance(dato, str):
        if dato.strip():
            acumulado.append(dato)
    elif isinstance(dato, dict):
        for valor in dato.values():
            _recolectar_strings(valor, acumulado, profundidad + 1)
    elif isinstance(dato, (list, tuple)):
        for valor in dato:
            _recolectar_strings(valor, acumulado, profundidad + 1)


def _mensaje_a_texto(mensaje: Any) -> str:
    """Aplana un DirectMessage de instagrapi a un unico bloque de texto."""
    try:
        crudo = mensaje.model_dump()
    except AttributeError:
        crudo = getattr(mensaje, "__dict__", {}) or {}
    partes: list[str] = []
    _recolectar_strings(crudo, partes)
    vistos: set[str] = set()
    unicas = [p for p in partes if not (p in vistos or vistos.add(p))]
    return "\n".join(unicas)


def _es_del_bot(mensaje: Any, mi_user_id: str) -> bool:
    propio = getattr(mensaje, "is_sent_by_viewer", None)
    if propio is not None:
        return not propio
    remitente = str(getattr(mensaje, "user_id", "") or "")
    return bool(remitente) and remitente != str(mi_user_id)


def _ts_utc(mensaje: Any) -> datetime | None:
    """Timestamp del mensaje normalizado a UTC.

    instagrapi entrega un datetime *naive en hora local* (verificado contra una
    corrida real: un DM naive 02:22:35 con la maquina en UTC-6 corresponde a
    08:22:35Z). Sin esta normalizacion la comparacion contra `commented_at`
    (que si es UTC) se corre por el offset de la maquina.
    """
    crudo = getattr(mensaje, "timestamp", None)
    if not isinstance(crudo, datetime):
        return None
    if crudo.tzinfo is None:
        crudo = crudo.astimezone()
    return crudo.astimezone(timezone.utc)


def _a_utc(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        momento = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(timezone.utc)


def _pide_follow(texto: str) -> bool:
    minuscula = texto.lower()
    return any(frase in minuscula for frase in _PIDE_FOLLOW)


def _seguir_al_autor(session: InstagramSession, user_id: str, autor: str) -> bool:
    """Sigue al autor. ACCION PUBLICA: el follow queda visible en la cuenta.

    Solo se llama con `comments.auto_follow` activo y cuando el bot dijo
    explicitamente que sin seguirlo no manda el recurso.
    """
    try:
        con_reintentos(
            lambda: session.client.user_follow(int(user_id)),
            max_retries=2,
            descripcion=f"seguir a {autor}",
        )
    except Exception as exc:  # noqa: BLE001
        propio = clasificar_error(exc)
        if propio is not None:
            raise propio from exc
        log.warning("follow_fallido", autor=autor, error=str(exc)[:200])
        return False
    log.info("autor_seguido", autor=autor, motivo="el bot lo exigia")
    return True


def _botones_cta(mensaje: Any) -> list[dict[str, str]]:
    """Botones del template del bot: [{'titulo': ..., 'tipo': ...}, ...].

    Viven en `raw_xma.generic_xma[].cta_buttons[]`, fuera del modelo tipado de
    instagrapi. Los bots tipo ManyChat mandan aca el 'Send me the guide' que
    hay que pulsar para que suelten el enlace.
    """
    try:
        crudo = mensaje.model_dump()
    except AttributeError:
        crudo = getattr(mensaje, "__dict__", {}) or {}

    plantillas = (crudo.get("raw_xma") or {}).get("generic_xma") or []
    botones: list[dict[str, str]] = []
    for plantilla in plantillas:
        if not isinstance(plantilla, dict):
            continue
        for boton in plantilla.get("cta_buttons") or []:
            if not isinstance(boton, dict):
                continue
            titulo = str(boton.get("title") or "").strip()
            if titulo:
                botones.append(
                    {"titulo": titulo, "tipo": str(boton.get("cta_type") or "")}
                )
    return botones


def _hilo_en_pendientes(session: InstagramSession, user_id: str) -> str | None:
    """Busca el hilo en 'solicitudes de mensaje' y lo aprueba para poder leerlo.

    Si la cuenta del post no te sigue, su DM cae aca y NO aparece en la bandeja
    normal. Sin este paso el enlace se perderia en silencio.
    """
    try:
        pendientes = session.client.direct_pending_inbox(amount=20)
    except Exception as exc:  # noqa: BLE001
        log.debug("pendientes_no_leidos", error=str(exc)[:200])
        return None

    for hilo in pendientes:
        participantes = {str(getattr(u, "pk", "")) for u in getattr(hilo, "users", [])}
        if str(user_id) not in participantes:
            continue
        thread_id = str(getattr(hilo, "id", "") or "")
        if not thread_id:
            continue
        try:
            session.client.direct_pending_approve(int(thread_id))
            log.info("solicitud_dm_aceptada", thread_id=thread_id)
        except Exception as exc:  # noqa: BLE001
            # Aun sin aprobar suele poder leerse; se sigue igual.
            log.warning("aprobacion_fallida", thread_id=thread_id, error=str(exc)[:200])
        return thread_id
    return None


def buscar_hilo(session: InstagramSession, autor: str) -> tuple[str, str] | None:
    """Devuelve (thread_id, user_id) del hilo con ese autor, si existe.

    Mira primero la bandeja normal y despues las solicitudes de mensaje.
    """
    try:
        user_id = con_reintentos(
            lambda: session.client.user_id_from_username(autor),
            max_retries=3,
            descripcion=f"resolver usuario {autor}",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("usuario_no_resuelto", autor=autor, error=str(exc)[:200])
        return None

    thread_id = ""
    try:
        hilo = session.client.direct_thread_by_participants([int(user_id)])
        if isinstance(hilo, dict):
            thread = hilo.get("thread") or hilo
            thread_id = str(thread.get("thread_id") or thread.get("id") or "")
        else:
            thread_id = str(getattr(hilo, "id", "") or "")
    except Exception as exc:  # noqa: BLE001
        log.debug("hilo_no_encontrado_en_bandeja", autor=autor, error=str(exc)[:200])

    if not thread_id:
        thread_id = _hilo_en_pendientes(session, str(user_id)) or ""

    return (thread_id, str(user_id)) if thread_id else None


def leer_mensajes_nuevos(
    session: InstagramSession,
    thread_id: str,
    mi_id: str,
    vistos: set[str],
    desde: datetime | None = None,
) -> list[Any]:
    """Mensajes del bot que todavia no se procesaron, del mas viejo al mas nuevo.

    `desde` descarta lo anterior a ese momento (UTC). Es imprescindible cuando
    un mismo autor tiene varios posts en la coleccion: el hilo de DM es por
    autor, no por post, asi que sin el filtro la respuesta de un post viejo se
    atribuye al comentario recien publicado.
    """
    mensajes = con_reintentos(
        lambda: session.client.direct_messages(thread_id, amount=20),
        max_retries=3,
        descripcion="leer DMs",
    )
    nuevos = [
        m
        for m in reversed(list(mensajes))
        if _es_del_bot(m, mi_id)
        and str(getattr(m, "id", "")) not in vistos
        and (desde is None or (_ts_utc(m) or desde) >= desde)
    ]
    for mensaje in nuevos:
        vistos.add(str(getattr(mensaje, "id", "")))
    return nuevos


def revisar_dm_una_vez(
    session: InstagramSession,
    item: SavedItem,
    dm: DmResult,
    extraer_urls: Callable[[str], list[str]],
) -> DmResult:
    """Una sola pasada por el hilo, sin esperar.

    Sirve para recuperar los DMs que llegaron despues del timeout de la corrida
    en la que se comento: se revisan al inicio de la corrida siguiente.
    """
    objetivo = buscar_hilo(session, item.author)
    if objetivo is None:
        return dm
    thread_id, _ = objetivo
    mi_id = str(getattr(session.client, "user_id", "") or "")

    try:
        nuevos = leer_mensajes_nuevos(
            session, thread_id, mi_id, set(), desde=_a_utc(dm.commented_at)
        )
    except Exception as exc:  # noqa: BLE001
        propio = clasificar_error(exc)
        if propio is not None:
            raise propio from exc
        log.warning(
            "relectura_dm_fallida", shortcode=item.shortcode, error=str(exc)[:200]
        )
        return dm

    if not nuevos:
        return dm

    texto = "\n\n".join(_mensaje_a_texto(m) for m in nuevos)
    dm.dm_text = (dm.dm_text + "\n\n" + texto).strip() if dm.dm_text else texto
    urls = extraer_urls(dm.dm_text)
    if urls:
        dm.estado = "received"
        dm.dm_received_at = utcnow_iso()
        dm.dm_links = urls
        log.info("dm_tardio_recuperado", shortcode=item.shortcode, enlaces=len(urls))
    return dm


def esperar_dm(
    session: InstagramSession,
    config: Config,
    item: SavedItem,
    dm: DmResult,
    extraer_urls: Callable[[str], list[str]],
    responder: Callable[[str], str | None] | None = None,
    ventana: int | None = None,
) -> DmResult:
    """Sondea el inbox esperando el DM del autor del post.

    `extraer_urls` saca los enlaces del texto; `responder` (opcional) decide que
    contestar cuando el bot pide una interaccion para seguir el flujo. `ventana`
    acorta la espera (se usa al reintentar posts ya comentados en corridas
    anteriores, donde no hace falta el tope completo).
    """
    limite_total = ventana or config.comments.dm_wait_max_seconds
    intervalos = list(config.comments.dm_poll_intervals) or [30]
    mi_id = str(getattr(session.client, "user_id", "") or "")
    inicio = time.monotonic()
    vistos: set[str] = set()
    turnos = dm.turnos
    desde = _a_utc(dm.commented_at)
    seguido = False

    log.info(
        "esperando_dm",
        shortcode=item.shortcode,
        autor=item.author,
        tope_segundos=limite_total,
    )

    indice = 0
    while time.monotonic() - inicio < limite_total:
        espera = intervalos[min(indice, len(intervalos) - 1)]
        indice += 1
        restante = limite_total - (time.monotonic() - inicio)
        time.sleep(max(1.0, min(espera, restante)))

        objetivo = buscar_hilo(session, item.author)
        if objetivo is None:
            log.debug("sin_hilo_todavia", shortcode=item.shortcode)
            continue
        thread_id, _user_id = objetivo

        try:
            nuevos = leer_mensajes_nuevos(session, thread_id, mi_id, vistos, desde=desde)
        except Exception as exc:  # noqa: BLE001
            propio = clasificar_error(exc)
            if propio is not None:
                raise propio from exc
            log.warning("lectura_dm_fallida", error=str(exc)[:200])
            continue

        if not nuevos:
            continue

        texto = "\n\n".join(_mensaje_a_texto(m) for m in nuevos)
        dm.dm_text = (dm.dm_text + "\n\n" + texto).strip() if dm.dm_text else texto
        urls = extraer_urls(dm.dm_text)

        if urls:
            dm.estado = "received"
            dm.dm_received_at = utcnow_iso()
            dm.dm_links = urls
            dm.turnos = turnos
            log.info("dm_recibido", shortcode=item.shortcode, enlaces=len(urls))
            return dm

        # No hay enlace todavia. Primero el follow: varios bots no sueltan nada
        # hasta que los seguis, asi que responder el boton antes seria inutil.
        if (
            not seguido
            and config.comments.auto_follow
            and _pide_follow(texto)
            and _seguir_al_autor(session, _user_id, item.author)
        ):
            seguido = True
            # El reloj arranca de nuevo: la ventana se gasto esperando este
            # mensaje, y el bot recien ahora tiene con que reaccionar.
            inicio = time.monotonic()
            indice = 0
            continue

        # Si mando un boton, se contesta con su etiqueta literal: instagrapi no
        # sabe pulsar un postback, pero estos bots suelen aceptar el mismo texto
        # como disparador. Un titulo inventado por la IA no matchea nunca.
        botones = [b for m in nuevos for b in _botones_cta(m)]
        etiqueta = botones[0]["titulo"] if botones else None

        minuscula = texto.lower()
        pide = etiqueta is not None or any(s in minuscula for s in _PIDE_RESPUESTA)
        puede = etiqueta is not None or responder is not None
        if puede and pide and turnos < config.comments.dm_max_turns:
            respuesta = etiqueta or (responder(texto) if responder else None)
            if respuesta:
                try:
                    session.client.direct_send(respuesta, thread_ids=[thread_id])
                    turnos += 1
                    dm.turnos = turnos
                    # Igual que con el follow: se le da al bot su propia ventana
                    # para contestar, no lo que sobro de la anterior.
                    inicio = time.monotonic()
                    indice = 0
                    log.info(
                        "dm_respondido",
                        shortcode=item.shortcode,
                        respuesta=respuesta[:60],
                        turno=turnos,
                        origen="boton" if etiqueta else "ia",
                    )
                except Exception as exc:  # noqa: BLE001
                    propio = clasificar_error(exc)
                    if propio is not None:
                        raise propio from exc
                    log.warning("respuesta_dm_fallida", error=str(exc)[:200])

    if dm.estado != "received":
        dm.estado = "timeout"
    dm.turnos = turnos
    log.warning(
        "dm_sin_respuesta",
        shortcode=item.shortcode,
        autor=item.author,
        esperado_s=limite_total,
        detalle="Se reintentara al inicio de la proxima corrida",
    )
    return dm
