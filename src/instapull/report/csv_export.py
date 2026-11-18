"""Exportacion a CSV (una fila por elemento)."""

from __future__ import annotations

import csv
from pathlib import Path

from ..logging_setup import get_logger
from ..models import ProcessedItem

log = get_logger(__name__)

CABECERAS = [
    "shortcode",
    "titulo",
    "categoria",
    "valoracion",
    "autor",
    "fecha",
    "resumen",
    "herramientas",
    "repos",
    "enlaces",
    "etiquetas",
    "dm_estado",
    "dm_palabra",
    "permalink",
]


def generar_csv(items: list[ProcessedItem], destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig y ';' para que Excel en Windows lo abra bien de una
    with destino.open("w", newline="", encoding="utf-8-sig") as fh:
        escritor = csv.writer(fh, delimiter=";")
        escritor.writerow(CABECERAS)
        for p in items:
            a = p.analysis
            escritor.writerow(
                [
                    p.item.shortcode,
                    a.titulo if a else "",
                    a.categoria.value if a else "",
                    a.valoracion if a else "",
                    p.item.author,
                    (p.item.taken_at or "")[:10],
                    (a.resumen if a else "").replace("\n", " "),
                    " | ".join(a.herramientas) if a else "",
                    " | ".join(a.repos) if a else "",
                    " | ".join(a.enlaces) if a else "",
                    " | ".join(a.etiquetas) if a else "",
                    p.dm.estado,
                    p.dm.keyword or "",
                    p.item.permalink,
                ]
            )
    log.info("informe_csv", archivo=str(destino), elementos=len(items))
    return destino
