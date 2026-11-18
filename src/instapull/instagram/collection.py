"""Resolucion de la coleccion de guardados POR NOMBRE y listado de elementos."""

from __future__ import annotations

from typing import Any, Callable, Iterator

from instagrapi.extractors import extract_media_v1

from ..config import Config
from ..logging_setup import get_logger
from ..models import MediaType, SavedItem
from .auth import InstagramSession
from .ratelimit import InstaPullError, con_reintentos, pausa

log = get_logger(__name__)

# instagrapi: 1 = foto, 2 = video/reel, 8 = carrusel
_TIPOS = {1: MediaType.IMAGE, 2: MediaType.VIDEO, 8: MediaType.CAROUSEL}


class CollectionNotFound(InstaPullError):
    """No existe una coleccion con ese nombre en la cuenta."""


def _fecha_iso(valor: Any) -> str:
    if valor is None:
        return ""
    iso = getattr(valor, "isoformat", None)
    return iso() if callable(iso) else str(valor)


def media_a_item(media: Any) -> SavedItem:
    """Convierte un objeto Media de instagrapi en nuestro SavedItem."""
    code = getattr(media, "code", "") or ""
    usuario = getattr(media, "user", None)
    return SavedItem(
        shortcode=code,
        media_id=str(getattr(media, "pk", "") or getattr(media, "id", "")),
        author=getattr(usuario, "username", "") or "",
        taken_at=_fecha_iso(getattr(media, "taken_at", None)),
        caption=getattr(media, "caption_text", "") or "",
        permalink=f"https://www.instagram.com/p/{code}/" if code else "",
        media_type=_TIPOS.get(getattr(media, "media_type", 0), MediaType.UNKNOWN),
        video_duration=getattr(media, "video_duration", None),
    )


def buscar_coleccion(session: InstagramSession, nombre: str) -> str:
    """Devuelve el id de la coleccion cuyo nombre coincide (sin distinguir mayusculas)."""
    colecciones = con_reintentos(
        session.client.collections, descripcion="listar colecciones"
    )
    disponibles = []
    for col in colecciones:
        titulo = getattr(col, "name", "") or ""
        disponibles.append(titulo)
        if titulo.strip().lower() == nombre.strip().lower():
            log.info("coleccion_encontrada", nombre=titulo, id=str(col.id))
            return str(col.id)
    raise CollectionNotFound(
        f"No encontre la coleccion '{nombre}'. Colecciones disponibles: "
        + (", ".join(disponibles) or "(ninguna)")
    )


def _pagina(
    session: InstagramSession, config: Config, coleccion_id: str, max_id: str
) -> tuple[list[Any], str]:
    """Una pagina cruda de la coleccion y el cursor de la siguiente ("" si no hay mas).

    `collection_medias(last_media_pk=...)` de instagrapi NO pagina: arranca siempre
    desde el principio y solo corta al encontrar ese pk. Por eso vamos directo al
    endpoint con el cursor `max_id`.
    """

    def _traer() -> dict[str, Any]:
        params = {"max_id": max_id} if max_id else {}
        # "*" = todos los guardados, no una coleccion puntual
        endpoint = (
            "feed/saved/posts/" if coleccion_id == "*" else f"feed/collection/{coleccion_id}/"
        )
        return session.client.private_request(endpoint, params=params)

    resultado = con_reintentos(
        _traer,
        max_retries=config.instagram.max_retries,
        descripcion="listar pagina de la coleccion",
    )
    medias = [
        extract_media_v1(bruto.get("media", bruto))
        for bruto in resultado.get("items") or []
    ]
    siguiente = str(resultado.get("next_max_id") or "")
    if not resultado.get("more_available"):
        siguiente = ""
    return medias, siguiente


def iter_collection(
    session: InstagramSession,
    config: Config,
    limite: int | None = None,
    omitir: Callable[[str], bool] | None = None,
    cortar: Callable[[str], bool] | None = None,
) -> Iterator[tuple[SavedItem, Any]]:
    """Itera `(SavedItem, media_crudo)` de la coleccion, del mas nuevo al mas viejo.

    Pagina con el cursor `max_id` hasta juntar `limite` elementos que NO haya
    que omitir, para que el modo incremental alcance los posts mas antiguos de
    una coleccion grande en vez de quedarse siempre en la primera pagina.
    """
    nombre = config.instagram.collection_name
    tope = limite if limite is not None else config.instagram.max_items_per_run
    coleccion_id = "*" if nombre.strip() == "*" else buscar_coleccion(session, nombre)

    entregados = 0
    max_id = ""
    cursores: set[str] = set()
    vistos: set[str] = set()

    while entregados < tope:
        pagina, max_id = _pagina(session, config, coleccion_id, max_id)
        log.info(
            "pagina_listada", nombre=nombre, elementos=len(pagina), entregados=entregados
        )

        for media in pagina:
            item = media_a_item(media)
            if not item.shortcode or item.shortcode in vistos:
                continue
            vistos.add(item.shortcode)

            if cortar is not None and cortar(item.shortcode):
                log.info("corte_en_conocido", shortcode=item.shortcode)
                return

            if omitir is not None and omitir(item.shortcode):
                continue

            yield item, media
            entregados += 1
            if entregados >= tope:
                return
            pausa(config.instagram.request_delay_seconds, motivo="listado")

        if not pagina or not max_id or max_id in cursores:
            break  # ultima pagina (o cursor repetido: cortar antes de un bucle infinito)
        cursores.add(max_id)
        pausa(config.instagram.request_delay_seconds, motivo="pagina")
