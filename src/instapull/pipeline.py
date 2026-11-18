"""Orquestador: recorre la coleccion y procesa cada elemento de punta a punta.

Regla de oro: el fallo de un elemento nunca aborta la corrida completa. Solo
las senales de bloqueo o rate limit de Instagram detienen todo, y lo hacen
guardando el progreso.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ai.analyzer import analizar_elemento, responder_dm_con_ia
from .ai.client import AIClient
from .ai.requisitos import detectar_requisitos
from .config import Config
from .db import Database
from .instagram import acciones
from .instagram.auth import InstagramSession
from .instagram.collection import iter_collection
from .instagram.comments import (
    ContadorComentarios,
    LimiteComentarios,
    publicar_comentario,
)
from .instagram.dms import esperar_dm, revisar_dm_una_vez
from .instagram.downloader import descargar_medio, ruta_video, rutas_imagen
from .instagram.ratelimit import ActionBlocked, RateLimited, SessionExpired, pausa
from .links.resolver import extraer_urls, resolver_enlaces
from .logging_setup import get_logger
from .media.frames import extraer_audio, extraer_frames, ffmpeg_disponible
from .media.ocr import ocr_de_imagenes
from .media.transcribe import transcribir
from .models import (
    ItemStatus,
    MediaContext,
    PostRequisitos,
    ProcessedItem,
    SavedItem,
)
from .youtube.playlist import descargar_video, listar_playlist

log = get_logger(__name__)

# Espera al reintentar un post ya comentado en una corrida anterior. Corta a
# proposito: el bot responde en segundos o no responde.
_VENTANA_REINTENTO_DM = 90


@dataclass
class ResumenCorrida:
    procesados: int = 0
    salteados: int = 0
    errores: int = 0
    comentarios: int = 0
    dms_recuperados: int = 0
    detenida_por: str = ""
    planificados: list[dict[str, Any]] = field(default_factory=list)


def _preparar_media(item: SavedItem, config: Config) -> MediaContext:
    """Fotogramas, transcripcion y OCR del elemento ya descargado."""
    contexto = MediaContext()
    carpeta = (
        Path(item.media_dir) if item.media_dir else config.media_root / item.shortcode
    )

    video = ruta_video(item)
    if video and video.exists():
        if ffmpeg_disponible():
            frames = extraer_frames(video, carpeta / "frames", config.media)
            contexto.frames = [str(f) for f in frames]
            audio = extraer_audio(video, carpeta / "audio.wav")
            if audio:
                contexto.transcript = transcribir(audio, config.media)
        else:
            log.warning(
                "sin_ffmpeg",
                shortcode=item.shortcode,
                detalle="No se extraen fotogramas ni audio; se usa solo la portada",
            )

    if not contexto.frames:
        contexto.frames = [str(p) for p in rutas_imagen(item)][
            : config.media.max_frames_per_video
        ]

    contexto.ocr_text = ocr_de_imagenes(
        [Path(f) for f in contexto.frames], activo=config.media.ocr_enabled
    )
    contexto.duration = item.video_duration
    return contexto


def _cumplir_requisitos(
    session: InstagramSession,
    config: Config,
    item: SavedItem,
    req: PostRequisitos,
) -> None:
    """Ejecuta las acciones que el post exige, si estan habilitadas.

    Cada una tiene su propia llave en config: nada se hace de forma preventiva,
    solo cuando el caption lo pide explicitamente. Lo que quede sin permiso se
    registra igual, para que se vea en el informe por que no se cumplio.
    """
    permisos = {
        "seguir": config.comments.auto_follow,
        "like": config.comments.auto_like,
        "guardar": config.comments.auto_save,
    }

    for requisito in req.requisitos:
        if requisito not in acciones.EJECUTABLES or requisito in req.cumplidos:
            continue
        if not permisos.get(requisito):
            log.info(
                "requisito_sin_permiso",
                shortcode=item.shortcode,
                requisito=requisito,
                detalle=f"activalo con comments.auto_{requisito} en config.yaml",
            )
            continue

        if requisito == "seguir":
            hecho = acciones.seguir_por_username(session, item.author)
        elif requisito == "like":
            hecho = acciones.dar_like(session, item.media_id, item.shortcode)
        else:
            hecho = acciones.guardar_post(session, item.media_id, item.shortcode)

        if hecho:
            req.cumplidos.append(requisito)


def _flujo_comentario_dm(
    session: InstagramSession,
    db: Database,
    config: Config,
    cliente: AIClient,
    procesado: ProcessedItem,
    contador: ContadorComentarios,
) -> None:
    """Elige la via mas barata y, si hace falta interactuar, la ejecuta.

    Orden deliberado: si el enlace ya esta en el caption no se toca nada. Si hay
    que comentar, primero se cumplen los requisitos previos (seguir, like), que
    son los que condicionan que el bot conteste, y recien despues se comenta.
    """
    item = procesado.item
    req = detectar_requisitos(item.caption, extraer_urls, cliente)
    procesado.requisitos = req
    db.save_requisitos(item.shortcode, req)

    if req.via == "directa" and config.comments.preferir_via_directa:
        log.info(
            "sin_interaccion",
            shortcode=item.shortcode,
            motivo="el post ya trae el enlace",
            enlaces=len(req.urls_directas),
        )
        return

    if req.via != "comentario" or not req.palabra:
        return

    log.info(
        "consigna_detectada",
        shortcode=item.shortcode,
        palabra=req.palabra,
        requisitos=req.requisitos,
    )

    if not db.already_commented(item.shortcode):
        _cumplir_requisitos(session, config, item, req)
        db.save_requisitos(item.shortcode, req)

    dm = publicar_comentario(session, db, config, item, req.palabra, contador)
    procesado.dm = dm
    if dm.estado != "commented":
        return

    dm = esperar_dm(
        session,
        config,
        item,
        dm,
        extraer_urls=extraer_urls,
        responder=lambda texto: responder_dm_con_ia(cliente, texto),
    )
    procesado.dm = dm
    db.save_comment_action(item.shortcode, dm)


def recuperar_dms_tardios(
    session: InstagramSession,
    db: Database,
    config: Config,
    cliente: AIClient | None,
    interaccion_activa: bool = False,
) -> int:
    """Revisa los DMs que no habian llegado a tiempo en corridas anteriores.

    Nunca comenta. Si el bot habia quedado esperando algo (un boton sin pulsar o
    que lo siguieran), se reintenta el flujo con una ventana corta: sin esto, un
    post ya comentado no vuelve a pasar por `esperar_dm` y queda muerto para
    siempre. Si aparece el enlace, resuelve los destinos y reanaliza el elemento.
    """
    pendientes = db.pendientes_de_dm()
    if not pendientes:
        return 0

    log.info("revisando_dms_pendientes", cantidad=len(pendientes))
    recuperados = 0

    for item in pendientes:
        try:
            dm = db.get_comment_action(item.shortcode)
            dm = revisar_dm_una_vez(session, item, dm, extraer_urls)

            if dm.estado != "received" and interaccion_activa:
                # El bot quedo esperando: se le da otra pasada corta para
                # seguirlo y/o contestar su boton. No se comenta nada.
                dm = esperar_dm(
                    session,
                    config,
                    item,
                    dm,
                    extraer_urls=extraer_urls,
                    responder=(
                        (lambda texto: responder_dm_con_ia(cliente, texto))
                        if cliente is not None
                        else None
                    ),
                    ventana=_VENTANA_REINTENTO_DM,
                )
                db.save_comment_action(item.shortcode, dm)

            if dm.estado != "received":
                continue

            db.save_comment_action(item.shortcode, dm)
            recuperados += 1

            if cliente is None:
                continue

            # El DM trajo el recurso: se rehace el analisis con ese contexto
            procesado = ProcessedItem(item=item, dm=dm)
            urls = list(dict.fromkeys(extraer_urls(item.caption) + dm.dm_links))
            if urls:
                procesado.links = resolver_enlaces(urls, config.links)
                db.save_links(item.shortcode, procesado.links)
            procesado.media = _preparar_media(item, config)

            analisis = analizar_elemento(cliente, procesado)
            db.save_analysis(
                item.shortcode,
                analisis,
                transcript=procesado.media.transcript,
                ocr_text=procesado.media.ocr_text,
            )
            db.registrar_herramientas(item.shortcode, analisis, procesado.links)
            item.status = ItemStatus.ANALYZED
            db.upsert_item(item)
            log.info("reanalizado_con_dm", shortcode=item.shortcode)

        except (ActionBlocked, RateLimited, SessionExpired):
            raise
        except Exception as exc:  # noqa: BLE001 - aislamiento por elemento
            log.warning(
                "recuperacion_dm_fallida",
                shortcode=item.shortcode,
                error=str(exc)[:200],
            )

    return recuperados


def procesar_elemento(
    session: InstagramSession,
    db: Database,
    config: Config,
    cliente: AIClient,
    item: SavedItem,
    media_cruda: Any,
    comentarios_activos: bool,
    contador: ContadorComentarios,
) -> ProcessedItem:
    """Descarga, resuelve DM y enlaces, analiza y persiste un unico elemento."""
    procesado = ProcessedItem(item=item)

    # 1) Descarga
    descargar_medio(item, media_cruda, config)
    item.status = ItemStatus.DOWNLOADED
    db.upsert_item(item)

    # 2) Comentario -> DM (opcional)
    procesado.dm = db.get_comment_action(item.shortcode)
    if comentarios_activos:
        try:
            _flujo_comentario_dm(session, db, config, cliente, procesado, contador)
        except LimiteComentarios as exc:
            log.info("tope_comentarios", detalle=str(exc))

    # 3) Enlaces: los del caption + los que llegaron por DM
    urls = extraer_urls(item.caption) + list(procesado.dm.dm_links)
    unicas = list(dict.fromkeys(urls))
    if unicas:
        procesado.links = resolver_enlaces(unicas, config.links)
        db.save_links(item.shortcode, procesado.links)

    # 4) Medios: fotogramas, transcripcion, OCR
    procesado.media = _preparar_media(item, config)

    # 5) Analisis con IA
    analisis = analizar_elemento(cliente, procesado)
    procesado.analysis = analisis
    db.save_analysis(
        item.shortcode,
        analisis,
        transcript=procesado.media.transcript,
        ocr_text=procesado.media.ocr_text,
    )

    # 6) Catalogo global: lo ya visto suma una mencion en vez de duplicarse
    nuevas, repetidas = db.registrar_herramientas(
        item.shortcode, analisis, procesado.links
    )
    procesado.herramientas_repetidas = repetidas
    if nuevas or repetidas:
        log.info(
            "catalogo_actualizado",
            shortcode=item.shortcode,
            nuevas=len(nuevas),
            ya_conocidas=len(repetidas),
        )

    item.status = ItemStatus.ANALYZED
    item.error = None
    db.upsert_item(item)
    return procesado


def ejecutar_corrida(
    config: Config,
    db: Database,
    session: InstagramSession,
    cliente: AIClient | None,
    limite: int | None = None,
    force: bool = False,
    enable_comments: bool = False,
    max_comments: int | None = None,
    dry_run: bool = False,
) -> ResumenCorrida:
    """Recorre la coleccion configurada y procesa lo que corresponda."""
    resumen = ResumenCorrida()
    tope = limite if limite is not None else config.instagram.max_items_per_run
    comentarios_activos = enable_comments and config.comments.enabled
    if enable_comments and not config.comments.enabled:
        log.warning(
            "comentarios_desactivados_en_config",
            detalle="Pone comments.enabled: true en config.yaml para habilitarlos",
        )

    contador = ContadorComentarios(
        max_comments if max_comments is not None else config.comments.max_comments_per_run
    )
    run_id = db.start_run(nota="dry-run" if dry_run else "run")

    def _omitir(shortcode: str) -> bool:
        """Saltea lo ya analizado y lo cuenta, sin gastar un turno del tope."""
        if force or not db.is_analyzed(shortcode):
            return False
        resumen.salteados += 1
        log.debug("ya_procesado", shortcode=shortcode)
        return True

    # Con "*" (todos los guardados) solo interesa lo nuevo: el listado va del mas
    # nuevo al mas viejo, asi que se corta en el primer elemento analizado en una
    # corrida de un dia anterior.
    # chisle: corte por fecha de descarga, no por fecha de guardado (IG no la expone)
    cortar = None
    if config.instagram.collection_name.strip() == "*" and not force:
        hoy = datetime.now(timezone.utc).date().isoformat()
        viejos = {
            fila[0]
            for fila in db.conn.execute(
                "select shortcode from items where status = ? and downloaded_at < ?",
                (ItemStatus.ANALYZED.value, hoy),
            )
        }
        # La API no respeta el orden de la grilla: un post viejo puede aparecer
        # entre los nuevos. Se corta recien al ver varios viejos.
        vistos_viejos = [0]

        def cortar(shortcode: str) -> bool:
            if shortcode in viejos:
                vistos_viejos[0] += 1
            return vistos_viejos[0] >= 10

    try:
        # Primero, los DMs que llegaron tarde en corridas anteriores
        if not dry_run:
            resumen.dms_recuperados = recuperar_dms_tardios(
                session, db, config, cliente, interaccion_activa=comentarios_activos
            )

        for item, media_cruda in iter_collection(
            session, config, limite=tope, omitir=_omitir, cortar=cortar
        ):
            if resumen.procesados >= tope:
                log.info("tope_alcanzado", tope=tope)
                break

            if dry_run:
                # Sin cliente de IA: en el plan solo interesa la lectura barata
                req = detectar_requisitos(item.caption, extraer_urls, None)
                resumen.planificados.append(
                    {
                        "shortcode": item.shortcode,
                        "autor": item.author,
                        "tipo": item.media_type.value,
                        "permalink": item.permalink,
                        "caption": (item.caption or "")[:120].replace("\n", " "),
                        "via": req.via,
                        "requisitos": req.requisitos,
                        "comentaria": bool(
                            comentarios_activos
                            and req.via == "comentario"
                            and not db.already_commented(item.shortcode)
                        ),
                        "palabra": req.palabra,
                    }
                )
                resumen.procesados += 1
                continue

            if cliente is None:
                raise RuntimeError(
                    "Falta el cliente de IA: defini OPENROUTER_API_KEY para analizar."
                )

            try:
                procesar_elemento(
                    session,
                    db,
                    config,
                    cliente,
                    item,
                    media_cruda,
                    comentarios_activos,
                    contador,
                )
                resumen.procesados += 1
            except (ActionBlocked, RateLimited, SessionExpired):
                raise
            except Exception as exc:  # noqa: BLE001 - aislamiento por elemento
                resumen.errores += 1
                item.status = ItemStatus.ERROR
                item.error = str(exc)[:500]
                db.upsert_item(item)
                log.error(
                    "elemento_fallido",
                    shortcode=item.shortcode,
                    error=str(exc)[:300],
                    exc_info=True,
                )

            pausa(config.instagram.request_delay_seconds, motivo="entre elementos")

    except ActionBlocked as exc:
        resumen.detenida_por = f"accion bloqueada: {exc}"
        log.error("corrida_detenida", motivo=resumen.detenida_por)
    except RateLimited as exc:
        resumen.detenida_por = f"limite de peticiones: {exc}"
        log.error("corrida_detenida", motivo=resumen.detenida_por)
    except SessionExpired as exc:
        resumen.detenida_por = f"sesion expirada: {exc}"
        log.error("corrida_detenida", motivo=resumen.detenida_por)
    finally:
        resumen.comentarios = contador.publicados
        db.finish_run(run_id, resumen.procesados, resumen.errores, contador.publicados)

    return resumen


# --- Fuente YouTube ---------------------------------------------------
# Misma cadena de analisis que Instagram, sin sesion ni acciones publicas:
# una playlist propia hace de "coleccion de guardados".


def _media_youtube(
    item: SavedItem, config: Config, transcript_subs: str
) -> MediaContext:
    """Fotogramas + transcripcion de un video de YouTube ya descargado.

    Si el video trae subtitulos se usan tal cual: whisper sobre 20 minutos de
    audio tarda mas que todo el resto de la corrida junta.
    """
    contexto = MediaContext()
    carpeta = Path(item.media_dir) if item.media_dir else config.media_root
    media_cfg = config.media.model_copy(
        update={
            "frame_interval_seconds": config.youtube.frame_interval_seconds,
            "max_frames_per_video": config.youtube.max_frames_per_video,
        }
    )

    contexto.transcript = transcript_subs
    video = ruta_video(item)
    if video and video.exists():
        if ffmpeg_disponible():
            frames = extraer_frames(video, carpeta / "frames", media_cfg)
            contexto.frames = [str(f) for f in frames]
            if not contexto.transcript:
                audio = extraer_audio(video, carpeta / "audio.wav")
                if audio:
                    contexto.transcript = transcribir(audio, config.media)
        else:
            log.warning(
                "sin_ffmpeg",
                shortcode=item.shortcode,
                detalle="No se extraen fotogramas; se usa la portada y el texto",
            )

    if not contexto.frames:
        contexto.frames = [str(p) for p in rutas_imagen(item)][
            : media_cfg.max_frames_per_video
        ]

    contexto.ocr_text = ocr_de_imagenes(
        [Path(f) for f in contexto.frames], activo=config.media.ocr_enabled
    )
    contexto.duration = item.video_duration
    return contexto


def procesar_video(
    db: Database, config: Config, cliente: AIClient, item: SavedItem
) -> ProcessedItem:
    """Descarga, analiza y persiste un unico video de YouTube."""
    item, subs = descargar_video(item, config)
    item.status = ItemStatus.DOWNLOADED
    db.upsert_item(item)

    procesado = ProcessedItem(item=item)

    urls = list(dict.fromkeys(extraer_urls(item.caption)))
    if urls:
        procesado.links = resolver_enlaces(urls, config.links)
        db.save_links(item.shortcode, procesado.links)

    procesado.media = _media_youtube(item, config, subs)

    analisis = analizar_elemento(cliente, procesado)
    procesado.analysis = analisis
    db.save_analysis(
        item.shortcode,
        analisis,
        transcript=procesado.media.transcript,
        ocr_text=procesado.media.ocr_text,
    )

    nuevas, repetidas = db.registrar_herramientas(
        item.shortcode, analisis, procesado.links
    )
    procesado.herramientas_repetidas = repetidas

    item.status = ItemStatus.ANALYZED
    item.error = None
    db.upsert_item(item)
    return procesado


def ejecutar_corrida_youtube(
    config: Config,
    db: Database,
    cliente: AIClient | None,
    limite: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    playlist_url: str | None = None,
) -> ResumenCorrida:
    """Recorre la playlist configurada y procesa los videos nuevos."""
    resumen = ResumenCorrida()
    url = (playlist_url or config.youtube.playlist_url).strip()
    if not url:
        raise RuntimeError(
            "Falta la playlist: defini youtube.playlist_url en config.yaml "
            "o pasa --playlist <url>."
        )

    tope = limite if limite is not None else config.youtube.max_items_per_run
    tope_segundos = config.youtube.max_duration_minutes * 60
    run_id = db.start_run(nota="youtube dry-run" if dry_run else "youtube")

    try:
        # Se piden mas elementos de los que se van a procesar: los ya analizados
        # no gastan turno del tope.
        candidatos = listar_playlist(url, limite=max(tope * 3, tope + 10))

        for item in candidatos:
            if resumen.procesados >= tope:
                log.info("tope_alcanzado", tope=tope)
                break

            if not force and db.is_analyzed(item.shortcode):
                resumen.salteados += 1
                continue

            if item.video_duration and item.video_duration > tope_segundos:
                resumen.salteados += 1
                log.info(
                    "video_muy_largo",
                    shortcode=item.shortcode,
                    minutos=round(item.video_duration / 60, 1),
                    tope_minutos=config.youtube.max_duration_minutes,
                )
                continue

            if dry_run:
                resumen.planificados.append(
                    {
                        "shortcode": item.shortcode,
                        "autor": item.author,
                        "tipo": "youtube",
                        "permalink": item.permalink,
                        "caption": (item.caption or "")[:120].replace("\n", " "),
                        "via": "directa",
                        "requisitos": [],
                        "comentaria": False,
                        "palabra": None,
                    }
                )
                resumen.procesados += 1
                continue

            if cliente is None:
                raise RuntimeError(
                    "Falta el cliente de IA: usa ai.provider claude-cli o defini "
                    "OPENROUTER_API_KEY."
                )

            try:
                procesar_video(db, config, cliente, item)
                resumen.procesados += 1
            except Exception as exc:  # noqa: BLE001 - aislamiento por elemento
                resumen.errores += 1
                item.status = ItemStatus.ERROR
                item.error = str(exc)[:500]
                db.upsert_item(item)
                log.error(
                    "video_fallido",
                    shortcode=item.shortcode,
                    error=str(exc)[:300],
                    exc_info=True,
                )
    finally:
        db.finish_run(run_id, resumen.procesados, resumen.errores, 0)

    return resumen
