"""Que herramientas ya tiene el usuario en sus propios proyectos.

Lee las carpetas de proyectos del disco y saca de ahi lo que ya esta instalado
o clonado, para que el catalogo pueda marcar "esto ya lo tenes" y el usuario
solo mire lo que le falta.

Cuatro fuentes, de la mas confiable a la mas ruidosa:

    skill        `<proyecto>/.claude/skills/<nombre>/`
    mcp          servidores declarados en `<proyecto>/.mcp.json`
    repo         carpetas clonadas bajo una raiz tipo `skills/github/`
    dependencia  `dependencies` y `devDependencies` del package.json

Nunca se abre un lockfile ni node_modules: solo lo que el usuario eligio a
mano. Todo se reduce a la misma clave canonica que usa el catalogo, asi que
"@supabase/mcp-server-supabase" y un post que diga "Supabase" caen en la
misma fila.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .normalize import canonicalizar, nombre_legible

# Carpetas que nunca son un proyecto del usuario.
_IGNORAR = {
    "node_modules",
    ".git",
    ".next",
    "venv",
    ".venv",
    "__pycache__",
    "dist",
    "build",
}

# Ruido de empaquetado que estorba al comparar con el nombre del producto:
# "@supabase/mcp-server-supabase@latest" es, para el usuario, "Supabase".
_PREFIJOS_PAQUETE = ("mcp-server-", "server-", "create-")
_SUFIJOS_PAQUETE = ("-mcp", "-mcp-server", "-server", "-cli", "-js", "-py")


def _limpiar_paquete(bruto: str) -> str:
    """Reduce un paquete npm o un comando npx al nombre del producto."""
    nombre = bruto.strip()
    if not nombre or nombre.startswith("-"):
        return ""
    nombre = nombre.split("@latest")[0]
    # "@scope/paquete" -> "paquete"; un scope suelto ("@supabase") tambien sirve
    if nombre.startswith("@"):
        nombre = nombre[1:]
    if "/" in nombre:
        nombre = nombre.rsplit("/", 1)[-1]
    # Version pegada al final: "paquete@1.2.3"
    nombre = nombre.split("@")[0]

    for prefijo in _PREFIJOS_PAQUETE:
        if nombre.startswith(prefijo):
            nombre = nombre[len(prefijo) :]
    for sufijo in _SUFIJOS_PAQUETE:
        if nombre.endswith(sufijo) and len(nombre) > len(sufijo) + 2:
            nombre = nombre[: -len(sufijo)]
    return nombre.strip("-_ ")


def _leer_json(ruta: Path) -> dict[str, Any]:
    try:
        return json.loads(ruta.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        # Un package.json roto en un proyecto viejo no debe tumbar el escaneo
        return {}


def _subcarpetas(ruta: Path) -> list[Path]:
    if not ruta.is_dir():
        return []
    try:
        return [
            d
            for d in sorted(ruta.iterdir())
            if d.is_dir() and d.name not in _IGNORAR and not d.name.startswith(".")
        ]
    except OSError:
        return []


def _de_skills(proyecto: Path) -> Iterable[tuple[str, str]]:
    for carpeta in _subcarpetas(proyecto / ".claude" / "skills"):
        yield carpeta.name.replace("-", " "), "skill"


def _de_mcp(proyecto: Path) -> Iterable[tuple[str, str]]:
    datos = _leer_json(proyecto / ".mcp.json")
    servidores = datos.get("mcpServers")
    if not isinstance(servidores, dict):
        return
    for nombre, cfg in servidores.items():
        yield _limpiar_paquete(nombre), "mcp"
        args = cfg.get("args") if isinstance(cfg, dict) else None
        for arg in args or []:
            if isinstance(arg, str) and ("/" in arg or "@" in arg):
                yield _limpiar_paquete(arg), "mcp"


def _de_package(proyecto: Path) -> Iterable[tuple[str, str]]:
    datos = _leer_json(proyecto / "package.json")
    for bloque in ("dependencies", "devDependencies"):
        deps = datos.get(bloque)
        if isinstance(deps, dict):
            for paquete in deps:
                yield _limpiar_paquete(paquete), "dependencia"


def _de_repos(raiz: Path) -> Iterable[tuple[str, str, str]]:
    """Repos clonados: `skills/github/<repo>/`, dos niveles como maximo."""
    for grupo in _subcarpetas(raiz):
        for repo in _subcarpetas(grupo):
            yield repo.name.replace("-", " "), "repo", f"{raiz.name}/{grupo.name}"


def escanear(
    raices: Iterable[Path],
    raices_repos: Iterable[Path] = (),
    incluir_dependencias: bool = True,
) -> list[dict[str, str]]:
    """Recorre las raices y devuelve lo que el usuario ya tiene.

    Args:
        raices: carpetas que contienen proyectos (un nivel de subcarpetas).
        raices_repos: carpetas de repos clonados, agrupados en dos niveles
            (`skills/github/<repo>`). Van aparte porque en una raiz de
            proyectos ese barrido tomaria cada subcarpeta como un producto.

    Returns:
        Una entrada por herramienta y fuente, ya canonicalizada y sin ruido.
        La misma herramienta puede aparecer varias veces con distinto `origen`;
        la base se encarga de agruparlas.
    """
    hallazgos: list[dict[str, str]] = []

    def anotar(bruto: str, fuente: str, origen: str) -> None:
        clave = canonicalizar(bruto)
        if not clave:
            return
        hallazgos.append(
            {
                "clave": clave,
                "nombre": nombre_legible(bruto) or bruto,
                "fuente": fuente,
                "origen": origen,
            }
        )

    for raiz in raices_repos:
        raiz = Path(raiz)
        if raiz.is_dir():
            for bruto, fuente, origen in _de_repos(raiz):
                anotar(bruto, fuente, origen)

    for raiz in raices:
        raiz = Path(raiz)
        if not raiz.is_dir():
            continue

        extractores = [_de_skills, _de_mcp]
        if incluir_dependencias:
            extractores.append(_de_package)

        for proyecto in _subcarpetas(raiz):
            for extractor in extractores:
                for bruto, fuente in extractor(proyecto):
                    anotar(bruto, fuente, proyecto.name)

    return hallazgos
