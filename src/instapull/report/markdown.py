"""Informe en Markdown, agrupado por categoria y ordenado por valoracion."""

from __future__ import annotations

from pathlib import Path

from ..logging_setup import get_logger
from ..models import Categoria, ProcessedItem, utcnow_iso

log = get_logger(__name__)

ORDEN_CATEGORIAS = [
    Categoria.HERRAMIENTA_IA,
    Categoria.REPO_GITHUB,
    Categoria.TUTORIAL,
    Categoria.PRODUCTO_NEGOCIO,
    Categoria.OTRO,
]


def _estrellas(valoracion: int) -> str:
    """Estrellas unicode: los asteriscos romperian el formato Markdown."""
    n = max(1, min(5, valoracion))
    return "★" * n + "☆" * (5 - n)


def _ficha(procesado: ProcessedItem) -> str:
    item = procesado.item
    a = procesado.analysis
    assert a is not None

    lineas = [
        f"### {a.titulo or item.shortcode}",
        "",
        f"**Valoracion:** {_estrellas(a.valoracion)} ({a.valoracion}/5) | "
        f"**Autor:** @{item.author or '?'} | "
        f"**Fecha:** {(item.taken_at or '')[:10] or '?'}",
        "",
        a.resumen or "_Sin resumen._",
        "",
    ]

    if a.herramientas:
        lineas.append("**Herramientas:** " + ", ".join(a.herramientas))
    if a.repos:
        lineas.append("**Repos:** " + ", ".join(a.repos))

    if procesado.dm.estado == "received":
        lineas.append(
            f"**Obtenido por DM** (palabra comentada: `{procesado.dm.keyword}`)"
        )

    enlaces = []
    ya_listados: set[str] = set()
    for link in procesado.links:
        destino = link.url_final or link.url_original
        etiqueta = link.titulo or destino
        marca = " *(via DM)*" if destino in procesado.dm.dm_links else ""
        enlaces.append(f"  - [{etiqueta}]({destino}){marca}")
        ya_listados.add(destino)
    enlaces.extend(f"  - {u}" for u in a.enlaces if u not in ya_listados)
    if enlaces:
        lineas.append("**Enlaces:**")
        lineas.extend(enlaces)

    if a.etiquetas:
        lineas.append("**Etiquetas:** " + " ".join(f"`{t}`" for t in a.etiquetas))

    lineas.append(f"**Post original:** {item.permalink}")
    lineas.append("")
    return "\n".join(lineas)


def generar_markdown(items: list[ProcessedItem], destino: Path) -> Path:
    """Escribe el informe completo y devuelve la ruta del archivo."""
    destino.parent.mkdir(parents=True, exist_ok=True)

    por_categoria: dict[Categoria, list[ProcessedItem]] = {
        c: [] for c in ORDEN_CATEGORIAS
    }
    for procesado in items:
        if procesado.analysis is None:
            continue
        por_categoria.setdefault(procesado.analysis.categoria, []).append(procesado)

    total = sum(len(v) for v in por_categoria.values())
    partes = [
        "# Informe de la coleccion guardada",
        "",
        f"Generado: {utcnow_iso()[:19].replace('T', ' ')} UTC",
        f"Elementos analizados: **{total}**",
        "",
        "## Indice",
        "",
    ]
    for categoria in ORDEN_CATEGORIAS:
        cantidad = len(por_categoria.get(categoria, []))
        if cantidad:
            ancla = categoria.value.lower().replace(" ", "-")
            partes.append(f"- [{categoria.value}](#{ancla}) ({cantidad})")
    partes.append("")

    # Top general, util para decidir por donde empezar
    mejores = sorted(
        (p for p in items if p.analysis),
        key=lambda p: p.analysis.valoracion,  # type: ignore[union-attr]
        reverse=True,
    )[:10]
    if mejores:
        partes.append("## Lo mas aprovechable")
        partes.append("")
        for p in mejores:
            a = p.analysis
            assert a is not None
            partes.append(
                f"1. **{a.titulo or p.item.shortcode}** ({a.valoracion}/5) - "
                f"{a.categoria.value} - {p.item.permalink}"
            )
        partes.append("")

    for categoria in ORDEN_CATEGORIAS:
        grupo = sorted(
            por_categoria.get(categoria, []),
            key=lambda p: p.analysis.valoracion,  # type: ignore[union-attr]
            reverse=True,
        )
        if not grupo:
            continue
        partes.append(f"## {categoria.value}")
        partes.append("")
        partes.extend(_ficha(p) for p in grupo)

    destino.write_text("\n".join(partes), encoding="utf-8")
    log.info("informe_markdown", archivo=str(destino), elementos=total)
    return destino
