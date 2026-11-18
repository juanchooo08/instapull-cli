"""Vista interactiva del catalogo: un solo HTML autocontenido.

Sin CDN ni dependencias: el archivo tiene que abrir con doble clic, sin red, y
sobrevivir a viajar como adjunto de correo.

La tabla se escribe YA RELLENA desde Python y el JavaScript solo filtra y
ordena. Es a proposito: la previsualizacion de adjuntos de Gmail no ejecuta
scripts, y una tabla que se rellena sola al cargar se veria completamente
vacia ahi. Con las filas en el HTML, el peor caso es perder los filtros.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any

_PLANTILLA = """<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>InstaPull - catalogo de herramientas</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:24px; background:#0f1115; color:#e7e9ee;
         font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }}
  h1 {{ margin:0 0 4px 0; font-size:22px; }}
  .sub {{ color:#8b93a7; font-size:13px; margin-bottom:18px; }}
  .kpis {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:18px; }}
  .kpi {{ background:#171a21; border:1px solid #242835; border-radius:10px;
          padding:10px 14px; min-width:120px; }}
  .kpi b {{ display:block; font-size:22px; }}
  .kpi span {{ color:#8b93a7; font-size:12px; }}
  .barra {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }}
  input, select {{ background:#171a21; color:#e7e9ee; border:1px solid #242835;
                   border-radius:8px; padding:8px 10px; font-size:13px; }}
  input[type=search] {{ min-width:260px; flex:1; }}
  label.chk {{ display:flex; align-items:center; gap:6px; color:#8b93a7;
               background:#171a21; border:1px solid #242835; border-radius:8px;
               padding:8px 10px; font-size:13px; cursor:pointer; }}
  table {{ width:100%; border-collapse:collapse; background:#12151b;
           border:1px solid #242835; border-radius:10px; overflow:hidden; }}
  th {{ text-align:left; font-size:12px; text-transform:uppercase;
        letter-spacing:.4px; color:#8b93a7; background:#171a21;
        padding:10px 12px; cursor:pointer; user-select:none; }}
  th:hover {{ color:#e7e9ee; }}
  td {{ padding:10px 12px; border-top:1px solid #1d212b; vertical-align:top; }}
  tr:hover td {{ background:#161a22; }}
  a {{ color:#6ea8fe; text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  .tag {{ display:inline-block; font-size:11px; padding:2px 7px; border-radius:20px;
          background:#1e2430; color:#9fb0cc; margin:0 4px 4px 0; }}
  .nueva {{ background:#123524; color:#5fd39a; }}
  .rep {{ background:#3a2a12; color:#e0b063; }}
  .tengo {{ background:#2a2440; color:#b39ddb; }}
  .vacio {{ padding:28px; text-align:center; color:#8b93a7; }}
  .pie {{ margin-top:16px; color:#6f7789; font-size:12px; }}
</style></head>
<body>
<h1>Catalogo de herramientas</h1>
<div class="sub">InstaPull &middot; generado el {fecha} &middot; una fila por
herramienta, sin repetir: si vuelve a aparecer en otro post se suma al contador.</div>

<div class="kpis">
  <div class="kpi"><b id="kpi-total">{kpi_total}</b><span>herramientas unicas</span></div>
  <div class="kpi"><b id="kpi-nuevas">{kpi_nuevas}</b><span>nuevas ({dias_nuevo} dias)</span></div>
  <div class="kpi"><b id="kpi-rep">{kpi_rep}</b><span>vistas en 2+ posts</span></div>
  <div class="kpi"><b id="kpi-posts">{kpi_posts}</b><span>posts analizados</span></div>
  <div class="kpi"><b id="kpi-tengo">{kpi_tengo}</b><span>ya las tenes</span></div>
</div>

<noscript><div class="sub">Estas viendo el catalogo sin JavaScript (pasa en la
vista previa de adjuntos de Gmail): la tabla de abajo esta completa, pero el
buscador y los filtros no funcionan. Descarga el archivo y abrilo con doble
clic para tenerlos.</div></noscript>

<div class="barra">
  <input type="search" id="q" placeholder="Buscar herramienta, categoria o post...">
  <select id="cat"><option value="">Todas las categorias</option></select>
  <select id="tipo">
    <option value="">Herramientas y repos</option>
    <option value="herramienta">Solo herramientas</option>
    <option value="repo">Solo repos</option>
  </select>
  <select id="val">
    <option value="0">Cualquier valoracion</option>
    <option value="3">3+ estrellas</option>
    <option value="4">4+ estrellas</option>
    <option value="5">5 estrellas</option>
  </select>
  <label class="chk"><input type="checkbox" id="solonuevas"> Solo nuevas</label>
  <label class="chk"><input type="checkbox" id="solorep"> Solo repetidas</label>
  <label class="chk"><input type="checkbox" id="mefalta"> Solo las que me faltan</label>
</div>

<table id="tabla">
  <thead><tr>
    <th data-col="nombre">Herramienta</th>
    <th data-col="categoria">Categoria</th>
    <th data-col="valoracion_max">&#9733;</th>
    <th data-col="menciones">Posts</th>
    <th data-col="primera_vez">Primera vez</th>
    <th data-col="url">Enlace</th>
    <th data-col="_">Donde aparecio</th>
  </tr></thead>
  <tbody id="cuerpo">{cuerpo}</tbody>
</table>
<div class="vacio" id="vacio" hidden>Nada coincide con el filtro.</div>
<div class="pie">Generado por InstaPull. Los datos viven en data/instapull.db;
este archivo es una foto y se puede compartir tal cual.</div>

<script>
const DATOS = {datos};

let orden = {{ col: "menciones", asc: false }};
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g,
  (c) => ({{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }})[c]);

function categorias() {{
  const vistas = [...new Set(DATOS.map((d) => d.categoria).filter(Boolean))].sort();
  for (const c of vistas) {{
    const o = document.createElement("option");
    o.value = c; o.textContent = c; $("cat").appendChild(o);
  }}
}}

function filtrar() {{
  const q = $("q").value.trim().toLowerCase();
  const cat = $("cat").value, tipo = $("tipo").value;
  const val = parseInt($("val").value, 10) || 0;
  const nuevas = $("solonuevas").checked, rep = $("solorep").checked;
  const falta = $("mefalta").checked;
  return DATOS.filter((d) => {{
    if (cat && d.categoria !== cat) return false;
    if (tipo && d.tipo !== tipo) return false;
    if ((d.valoracion_max || 0) < val) return false;
    if (nuevas && !d.es_nueva) return false;
    if (rep && (d.menciones || 0) < 2) return false;
    if (falta && d.ya_tengo) return false;
    if (!q) return true;
    return (d.nombre + " " + (d.categoria || "") + " " + (d.url || "") + " " +
            (d.posts || []).map((p) => p.autor + " " + p.titulo).join(" "))
           .toLowerCase().includes(q);
  }});
}}

function pintar() {{
  const filas = filtrar().sort((a, b) => {{
    const x = a[orden.col], y = b[orden.col];
    const numerico = typeof x === "number" && typeof y === "number";
    const cmp = numerico ? x - y : String(x || "").localeCompare(String(y || ""));
    return orden.asc ? cmp : -cmp;
  }});

  $("cuerpo").innerHTML = filas.map((d) => `
    <tr>
      <td><b>${{esc(d.nombre)}}</b>
        ${{d.es_nueva ? '<span class="tag nueva">nueva</span>' : ""}}
        ${{(d.menciones || 0) > 1 ? `<span class="tag rep">x${{d.menciones}}</span>` : ""}}
        ${{d.ya_tengo ? `<span class="tag tengo"
           title="En tus proyectos: ${{esc((d.donde_la_tengo || []).join(", "))}}"
           >ya la tenes (${{esc(d.fuente_propia)}})</span>` : ""}}
      </td>
      <td>${{esc(d.categoria || "-")}}</td>
      <td>${{"&#9733;".repeat(d.valoracion_max || 0) || "-"}}</td>
      <td>${{d.menciones || 1}}</td>
      <td>${{esc((d.primera_vez || "").slice(0, 10))}}</td>
      <td>${{d.url ? `<a href="${{esc(d.url)}}" target="_blank" rel="noopener">abrir</a>` : "-"}}</td>
      <td>${{(d.posts || []).map((p) =>
        `<a href="${{esc(p.permalink)}}" target="_blank" rel="noopener"
            title="${{esc(p.titulo)}}">@${{esc(p.autor || "?")}}</a>`).join(", ")}}</td>
    </tr>`).join("");

  $("vacio").hidden = filas.length > 0;
  $("kpi-total").textContent = DATOS.length;
  $("kpi-nuevas").textContent = DATOS.filter((d) => d.es_nueva).length;
  $("kpi-rep").textContent = DATOS.filter((d) => (d.menciones || 0) > 1).length;
  $("kpi-posts").textContent =
    new Set(DATOS.flatMap((d) => (d.posts || []).map((p) => p.shortcode))).size;
  $("kpi-tengo").textContent = DATOS.filter((d) => d.ya_tengo).length;
}}

for (const th of document.querySelectorAll("th[data-col]")) {{
  th.addEventListener("click", () => {{
    const col = th.dataset.col;
    if (col === "_") return;
    orden = {{ col, asc: orden.col === col ? !orden.asc : true }};
    pintar();
  }});
}}
for (const id of ["q", "cat", "tipo", "val", "solonuevas", "solorep", "mefalta"]) {{
  $(id).addEventListener("input", pintar);
}}
categorias();
pintar();
</script>
</body></html>
"""


def _fila_html(d: dict[str, Any]) -> str:
    """Una fila de la tabla, identica a la que arma el JS al filtrar."""
    etiquetas = ""
    if d.get("es_nueva"):
        etiquetas += '<span class="tag nueva">nueva</span>'
    if (d.get("menciones") or 0) > 1:
        etiquetas += f'<span class="tag rep">x{int(d["menciones"])}</span>'
    if d.get("ya_tengo"):
        donde = escape(", ".join(d.get("donde_la_tengo") or []), quote=True)
        etiquetas += (
            f'<span class="tag tengo" title="En tus proyectos: {donde}">'
            f'ya la tenes ({escape(d.get("fuente_propia") or "")})</span>'
        )

    estrellas = "&#9733;" * int(d.get("valoracion_max") or 0) or "-"
    url = d.get("url") or ""
    enlace = (
        f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener">abrir</a>'
        if url
        else "-"
    )
    posts = ", ".join(
        f'<a href="{escape(p.get("permalink") or "", quote=True)}" target="_blank"'
        f' rel="noopener" title="{escape(p.get("titulo") or "", quote=True)}">'
        f'@{escape(p.get("autor") or "?")}</a>'
        for p in d.get("posts") or []
    )

    return (
        "<tr>"
        f'<td><b>{escape(d.get("nombre") or "")}</b> {etiquetas}</td>'
        f'<td>{escape(d.get("categoria") or "-")}</td>'
        f"<td>{estrellas}</td>"
        f'<td>{int(d.get("menciones") or 1)}</td>'
        f'<td>{escape((d.get("primera_vez") or "")[:10])}</td>'
        f"<td>{enlace}</td>"
        f"<td>{posts}</td>"
        "</tr>"
    )


def render_catalogo(
    filas: list[dict[str, Any]], fecha: str, dias_nuevo: int = 7
) -> str:
    """HTML autocontenido con todo el catalogo.

    La tabla y los contadores van escritos en el HTML, no generados al vuelo:
    asi el catalogo se lee igual donde no corre JavaScript (la vista previa de
    Gmail, por ejemplo), y el script solo agrega buscador, filtros y orden.

    Args:
        filas: salida de `Database.catalogo()`.
        fecha: dia de generacion (YYYY-MM-DD), para que sea determinista.
        dias_nuevo: cuantos dias hacia atras se considera "nueva".
    """
    datos = json.dumps(filas, ensure_ascii=False)
    # `</script>` dentro del JSON cerraria la etiqueta antes de tiempo
    datos = datos.replace("</", "<\\/")

    # Mismo orden por defecto que aplica el JS: primero lo mas visto
    ordenadas = sorted(
        filas,
        key=lambda d: (-(d.get("menciones") or 0), (d.get("nombre") or "").lower()),
    )
    posts_unicos = {
        p.get("shortcode")
        for d in filas
        for p in d.get("posts") or []
        if p.get("shortcode")
    }

    return _PLANTILLA.format(
        datos=datos,
        fecha=escape(fecha),
        dias_nuevo=int(dias_nuevo),
        cuerpo="\n".join(_fila_html(d) for d in ordenadas),
        kpi_total=len(filas),
        kpi_nuevas=sum(1 for d in filas if d.get("es_nueva")),
        kpi_rep=sum(1 for d in filas if (d.get("menciones") or 0) > 1),
        kpi_posts=len(posts_unicos),
        kpi_tengo=sum(1 for d in filas if d.get("ya_tengo")),
    )
