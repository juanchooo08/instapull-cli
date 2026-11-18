"""Cuerpo del digest: HTML para clientes de correo y texto plano de respaldo.

El HTML usa estilos en linea y una tabla de ancho fijo porque los clientes de
correo (sobre todo Outlook y Gmail) ignoran `<style>` y buena parte de CSS
moderno. Nada de esto es un sitio web: es lo minimo que se ve igual en todos.
"""

from __future__ import annotations

from html import escape

from ..models import Categoria, ProcessedItem
from ..report.markdown import ORDEN_CATEGORIAS, _estrellas


def _agrupar(items: list[ProcessedItem]) -> dict[Categoria, list[ProcessedItem]]:
    """Agrupa por categoria y ordena cada grupo por valoracion descendente."""
    grupos: dict[Categoria, list[ProcessedItem]] = {}
    for procesado in items:
        if procesado.analysis is None:
            continue
        grupos.setdefault(procesado.analysis.categoria, []).append(procesado)
    for grupo in grupos.values():
        grupo.sort(key=lambda p: p.analysis.valoracion, reverse=True)  # type: ignore[union-attr]
    return grupos


def _categorias_ordenadas(
    grupos: dict[Categoria, list[ProcessedItem]]
) -> list[Categoria]:
    conocidas = [c for c in ORDEN_CATEGORIAS if grupos.get(c)]
    otras = [c for c in grupos if c not in ORDEN_CATEGORIAS and grupos[c]]
    return conocidas + otras


def asunto_digest(items: list[ProcessedItem], fecha: str) -> str:
    """Asunto del correo. La fecha viene de afuera para que sea determinista."""
    cantidad = len(items)
    if cantidad == 1:
        return f"InstaPull {fecha}: 1 elemento nuevo"
    return f"InstaPull {fecha}: {cantidad} elementos nuevos"


def _enlaces_de(procesado: ProcessedItem) -> list[tuple[str, str, bool]]:
    """(etiqueta, url, vino_por_dm) sin duplicar los que ya se resolvieron."""
    salida: list[tuple[str, str, bool]] = []
    vistos: set[str] = set()
    for link in procesado.links:
        destino = link.url_final or link.url_original
        if not destino or destino in vistos:
            continue
        vistos.add(destino)
        salida.append((link.titulo or destino, destino, destino in procesado.dm.dm_links))
    if procesado.analysis:
        for url in procesado.analysis.enlaces:
            if url and url not in vistos:
                vistos.add(url)
                salida.append((url, url, False))
    return salida


def _ficha_html(procesado: ProcessedItem) -> str:
    item = procesado.item
    a = procesado.analysis
    assert a is not None

    partes = [
        '<div style="border:1px solid #e3e3e3;border-radius:6px;padding:14px;'
        'margin:0 0 12px 0;background:#ffffff;">',
        f'<div style="font-size:16px;font-weight:600;color:#111111;">'
        f"{escape(a.titulo or item.shortcode)}</div>",
        f'<div style="font-size:12px;color:#666666;margin:4px 0 10px 0;">'
        f"{_estrellas(a.valoracion)} ({a.valoracion}/5) &nbsp;&middot;&nbsp; "
        f"@{escape(item.author or '?')} &nbsp;&middot;&nbsp; "
        f"{escape((item.taken_at or '')[:10] or '?')}</div>",
        f'<div style="font-size:14px;color:#333333;line-height:1.5;">'
        f"{escape(a.resumen or 'Sin resumen.')}</div>",
    ]

    if a.herramientas:
        partes.append(
            '<div style="font-size:13px;color:#333333;margin-top:8px;">'
            f"<b>Herramientas:</b> {escape(', '.join(a.herramientas))}</div>"
        )
    if a.repos:
        partes.append(
            '<div style="font-size:13px;color:#333333;margin-top:4px;">'
            f"<b>Repos:</b> {escape(', '.join(a.repos))}</div>"
        )

    enlaces = _enlaces_de(procesado)
    if enlaces:
        filas = "".join(
            f'<li style="margin:2px 0;"><a href="{escape(url)}" '
            f'style="color:#1155cc;">{escape(etiqueta[:120])}</a>'
            + (' <span style="color:#888888;">(via DM)</span>' if via_dm else "")
            + "</li>"
            for etiqueta, url, via_dm in enlaces
        )
        partes.append(
            '<div style="font-size:13px;color:#333333;margin-top:8px;"><b>Enlaces:</b>'
            f'<ul style="margin:4px 0 0 18px;padding:0;">{filas}</ul></div>'
        )

    if a.etiquetas:
        partes.append(
            '<div style="font-size:12px;color:#666666;margin-top:8px;">'
            f"{escape(' '.join('#' + t for t in a.etiquetas))}</div>"
        )

    if item.permalink:
        partes.append(
            f'<div style="font-size:12px;margin-top:10px;">'
            f'<a href="{escape(item.permalink)}" style="color:#1155cc;">'
            "Ver el post original</a></div>"
        )

    partes.append("</div>")
    return "".join(partes)


def render_html(items: list[ProcessedItem], fecha: str) -> str:
    """Cuerpo HTML del digest."""
    grupos = _agrupar(items)
    cuerpo: list[str] = []
    for categoria in _categorias_ordenadas(grupos):
        cuerpo.append(
            '<h2 style="font-size:15px;text-transform:uppercase;letter-spacing:.5px;'
            'color:#888888;margin:22px 0 10px 0;">'
            f"{escape(categoria.value)} ({len(grupos[categoria])})</h2>"
        )
        cuerpo.extend(_ficha_html(p) for p in grupos[categoria])

    if not cuerpo:
        cuerpo.append(
            '<p style="font-size:14px;color:#666666;">Sin elementos nuevos.</p>'
        )

    return (
        '<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(asunto_digest(items, fecha))}</title></head>"
        '<body style="margin:0;padding:0;background:#f5f5f5;'
        'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#f5f5f5;padding:24px 12px;"><tr><td align="center">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        'style="max-width:600px;width:100%;text-align:left;">'
        '<tr><td style="padding:0 0 16px 0;">'
        '<div style="font-size:20px;font-weight:700;color:#111111;">InstaPull</div>'
        f'<div style="font-size:13px;color:#666666;">Resumen del {escape(fecha)} '
        f"&nbsp;&middot;&nbsp; {len(items)} elemento(s) nuevo(s)</div>"
        "</td></tr><tr><td>" + "".join(cuerpo) + "</td></tr>"
        '<tr><td style="padding:20px 0 0 0;font-size:11px;color:#999999;">'
        "Enviado por InstaPull. Para dejar de recibirlo, pone "
        "<code>email.enabled: false</code> en config.yaml."
        "</td></tr></table></td></tr></table></body></html>"
    )


def render_texto(items: list[ProcessedItem], fecha: str) -> str:
    """Version en texto plano, para clientes que no muestran HTML."""
    grupos = _agrupar(items)
    lineas = [
        f"InstaPull - resumen del {fecha}",
        f"{len(items)} elemento(s) nuevo(s)",
        "",
    ]

    for categoria in _categorias_ordenadas(grupos):
        lineas.append(f"== {categoria.value.upper()} ({len(grupos[categoria])})")
        lineas.append("")
        for procesado in grupos[categoria]:
            a = procesado.analysis
            assert a is not None
            item = procesado.item
            lineas.append(
                f"* {a.titulo or item.shortcode} ({a.valoracion}/5) - @{item.author}"
            )
            if a.resumen:
                lineas.append(f"  {a.resumen}")
            for _etiqueta, url, via_dm in _enlaces_de(procesado):
                lineas.append(f"  - {url}{' (via DM)' if via_dm else ''}")
            if item.permalink:
                lineas.append(f"  post: {item.permalink}")
            lineas.append("")

    if len(lineas) == 3:
        lineas.append("Sin elementos nuevos.")
    return "\n".join(lineas)
