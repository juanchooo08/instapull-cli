"""Exportacion a JSON."""

from __future__ import annotations

import json
from pathlib import Path

from ..logging_setup import get_logger
from ..models import ProcessedItem, utcnow_iso

log = get_logger(__name__)


def item_a_dict(procesado: ProcessedItem) -> dict:
    item = procesado.item
    a = procesado.analysis
    return {
        "shortcode": item.shortcode,
        "autor": item.author,
        "fecha": item.taken_at,
        "permalink": item.permalink,
        "tipo_medio": item.media_type.value,
        "caption": item.caption,
        "titulo": a.titulo if a else "",
        "resumen": a.resumen if a else "",
        "categoria": a.categoria.value if a else "",
        "valoracion": a.valoracion if a else None,
        "herramientas": a.herramientas if a else [],
        "repos": a.repos if a else [],
        "enlaces": a.enlaces if a else [],
        "etiquetas": a.etiquetas if a else [],
        "modelo": a.modelo if a else "",
        "dm": {
            "estado": procesado.dm.estado,
            "palabra": procesado.dm.keyword,
            "texto": procesado.dm.dm_text,
            "enlaces": procesado.dm.dm_links,
        },
        "enlaces_resueltos": [
            {
                "url_original": enlace.url_original,
                "url_final": enlace.url_final,
                "titulo": enlace.titulo,
                "tipo": enlace.tipo,
            }
            for enlace in procesado.links
        ],
        "media_dir": item.media_dir,
    }


def generar_json(items: list[ProcessedItem], destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    datos = {
        "generado": utcnow_iso(),
        "total": len(items),
        "elementos": [item_a_dict(p) for p in items],
    }
    destino.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("informe_json", archivo=str(destino), elementos=len(items))
    return destino
