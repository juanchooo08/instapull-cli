"""Interfaz de linea de comandos."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .ai.client import AIClient, AIError
from .catalog import escanear, render_catalogo
from .config import Config, load_config
from .db import Database
from .instagram.auth import InstagramSession
from .instagram.ratelimit import InstaPullError
from .logging_setup import setup_logging
from .media.frames import ffmpeg_disponible
from .notifications import EmailNotifier, debe_enviar_ahora
from .pipeline import ejecutar_corrida, ejecutar_corrida_youtube
from .report import generar_csv, generar_json, generar_markdown
from .youtube.playlist import YtDlpNoDisponible

app = typer.Typer(
    add_completion=False,
    help="Extrae y analiza los posts guardados de una coleccion de Instagram.",
)
consola = Console()


def _preparar(config_path: Path | None, verbose: bool) -> Config:
    config = load_config(config_path)
    config.ensure_dirs()
    setup_logging(config.log_path, verbose=verbose)
    return config


def _cliente_ia(config: Config) -> AIClient | None:
    try:
        return AIClient(config.ai, config.secrets.openrouter_api_key)
    except AIError as exc:
        consola.print(f"[yellow]Aviso:[/yellow] {exc}")
        return None


def _exportar(config: Config, db: Database) -> None:
    items = db.fetch_processed()
    if not items:
        consola.print("[yellow]No hay elementos analizados todavia.[/yellow]")
        return
    md = generar_markdown(items, config.output_dir / "informe.md")
    js = generar_json(items, config.output_dir / "items.json")
    cs = generar_csv(items, config.output_dir / "items.csv")
    consola.print(f"[green]Informe:[/green] {md}")
    consola.print(f"[green]JSON:[/green]    {js}")
    consola.print(f"[green]CSV:[/green]     {cs}")


@app.command()
def login(
    config_path: Path = typer.Option(None, "--config", help="Ruta a config.yaml"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Autentica contra Instagram y guarda la sesion para las proximas corridas."""
    config = _preparar(config_path, verbose)
    try:
        session = InstagramSession(config).login_interactivo()
    except InstaPullError as exc:
        consola.print(f"[red]No se pudo iniciar sesion:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    consola.print(
        f"[green]Sesion lista[/green] para @{session.username}. "
        f"Guardada en {config.session_path}"
    )


@app.command()
def run(
    config_path: Path = typer.Option(None, "--config", help="Ruta a config.yaml"),
    limit: int = typer.Option(None, "--limit", help="Tope de elementos de esta corrida"),
    force: bool = typer.Option(False, "--force", help="Reprocesa lo ya analizado"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Lista lo que haria, sin ejecutar nada"
    ),
    enable_comments: bool = typer.Option(
        False, "--enable-comments", help="Activa el modulo de comentario + DM"
    ),
    max_comments: int = typer.Option(
        None, "--max-comments", help="Tope de comentarios de esta corrida"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Recorre la coleccion, procesa los elementos nuevos y genera los informes."""
    config = _preparar(config_path, verbose)

    if not ffmpeg_disponible():
        consola.print(
            "[yellow]Aviso:[/yellow] no encuentro ffmpeg. Los videos se analizaran "
            "solo con su portada. Instalalo con: winget install Gyan.FFmpeg"
        )

    cliente = None if dry_run else _cliente_ia(config)
    if cliente is None and not dry_run:
        consola.print("[red]Falta OPENROUTER_API_KEY.[/red] Definila y volve a intentar.")
        raise typer.Exit(code=1)

    try:
        session = InstagramSession(config).connect(interactivo=False)
    except InstaPullError as exc:
        consola.print(f"[red]Sesion no disponible:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    with Database(config.db_path) as db:
        resumen = ejecutar_corrida(
            config=config,
            db=db,
            session=session,
            cliente=cliente,
            limite=limit,
            force=force,
            enable_comments=enable_comments,
            max_comments=max_comments,
            dry_run=dry_run,
        )

        if dry_run:
            tabla = Table(title="Plan de la corrida (dry-run: no se ejecuto nada)")
            tabla.add_column("Shortcode")
            tabla.add_column("Autor")
            tabla.add_column("Tipo")
            tabla.add_column("Via")
            tabla.add_column("Requisitos")
            tabla.add_column("Comentaria")
            tabla.add_column("Palabra")
            tabla.add_column("Caption", overflow="ellipsis", max_width=40)
            for plan in resumen.planificados:
                tabla.add_row(
                    plan["shortcode"],
                    f"@{plan['autor']}",
                    plan["tipo"],
                    plan["via"],
                    ", ".join(plan["requisitos"]) or "-",
                    "si" if plan["comentaria"] else "no",
                    plan["palabra"] or "-",
                    plan["caption"],
                )
            consola.print(tabla)
        else:
            _exportar(config, db)

    consola.print(
        f"\n[bold]Resumen:[/bold] {resumen.procesados} procesados, "
        f"{resumen.salteados} salteados, {resumen.errores} con error, "
        f"{resumen.comentarios} comentarios publicados, "
        f"{resumen.dms_recuperados} DM tardios recuperados."
    )
    if resumen.detenida_por:
        consola.print(f"[red]Corrida detenida:[/red] {resumen.detenida_por}")
        raise typer.Exit(code=2)


@app.command()
def youtube(
    config_path: Path = typer.Option(None, "--config", help="Ruta a config.yaml"),
    playlist: str = typer.Option(
        None, "--playlist", help="URL de la playlist (por defecto, la de config.yaml)"
    ),
    limit: int = typer.Option(None, "--limit", help="Tope de videos de esta corrida"),
    force: bool = typer.Option(False, "--force", help="Reprocesa lo ya analizado"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Lista los videos que bajaria, sin bajar nada"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Analiza los videos de una playlist de YouTube y los suma al mismo catalogo."""
    config = _preparar(config_path, verbose)

    if not ffmpeg_disponible():
        consola.print(
            "[yellow]Aviso:[/yellow] no encuentro ffmpeg. Sin el no hay fotogramas "
            "ni audio: el analisis queda solo con el titulo, la descripcion y los "
            "subtitulos."
        )

    cliente = None if dry_run else _cliente_ia(config)
    if cliente is None and not dry_run:
        consola.print("[red]No hay cliente de IA disponible.[/red]")
        raise typer.Exit(code=1)

    with Database(config.db_path) as db:
        try:
            resumen = ejecutar_corrida_youtube(
                config=config,
                db=db,
                cliente=cliente,
                limite=limit,
                force=force,
                dry_run=dry_run,
                playlist_url=playlist,
            )
        except (RuntimeError, YtDlpNoDisponible) as exc:
            consola.print(f"[red]No pude correr la playlist:[/red] {exc}")
            raise typer.Exit(code=1) from exc

        if dry_run:
            tabla = Table(title="Videos a procesar (dry-run: no se bajo nada)")
            tabla.add_column("Video")
            tabla.add_column("Canal")
            tabla.add_column("Titulo", overflow="ellipsis", max_width=60)
            for plan in resumen.planificados:
                tabla.add_row(plan["shortcode"], plan["autor"], plan["caption"])
            consola.print(tabla)
        else:
            _exportar(config, db)

    consola.print(
        f"\n[bold]Resumen:[/bold] {resumen.procesados} videos procesados, "
        f"{resumen.salteados} salteados, {resumen.errores} con error."
    )


@app.command()
def report(
    config_path: Path = typer.Option(None, "--config", help="Ruta a config.yaml"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Regenera los informes (Markdown, JSON, CSV) desde la base de datos."""
    config = _preparar(config_path, verbose)
    with Database(config.db_path) as db:
        _exportar(config, db)


@app.command()
def digest(
    config_path: Path = typer.Option(None, "--config", help="Ruta a config.yaml"),
    limit: int = typer.Option(
        None, "--limit", help="Tope de elementos en este correo (pisa email.max_items)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Muestra que se enviaria, sin mandar nada"
    ),
    force: bool = typer.Option(
        False, "--force", help="Ignora la hora configurada y el envio del dia"
    ),
    solo_catalogo: bool = typer.Option(
        False,
        "--solo-catalogo",
        help="Manda el catalogo aunque no haya posts nuevos que notificar",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Envia por correo el resumen de los elementos nuevos desde el ultimo envio."""
    config = _preparar(config_path, verbose)
    if limit:
        config.email.max_items = limit

    with Database(config.db_path) as db:
        if not force:
            ultimo = db.ultimo_digest()
            toca, motivo = debe_enviar_ahora(
                config.email, ultimo["sent_at"] if ultimo else None
            )
            if not toca:
                consola.print(f"[yellow]No se envia:[/yellow] {motivo}. "
                              "Usa --force para mandarlo igual.")
                return

        pendientes = db.pendientes_de_email()
        catalogo_filas = (
            db.catalogo(dias_nuevo=config.email.catalog_new_days)
            if config.email.attach_catalog
            else None
        )
        notifier = EmailNotifier(config.email, config.secrets.resend_api_key)
        resultado = notifier.send_daily_digest(
            pendientes,
            dry_run=dry_run,
            catalogo=catalogo_filas,
            solo_catalogo=solo_catalogo,
        )

        # Solo se registra lo que llego a intentarse de verdad: un dry-run o una
        # corrida sin novedades no deben marcar nada como notificado.
        if resultado.estado in ("sent", "error"):
            db.registrar_digest(
                resultado.shortcodes,
                asunto=resultado.asunto,
                estado=resultado.estado,
                message_id=resultado.message_id,
                error=resultado.error,
            )

    if resultado.estado == "sent":
        consola.print(
            f"[green]Correo enviado[/green] a {config.email.to_address}: "
            f"{resultado.asunto} ({resultado.detalle})"
        )
    elif resultado.estado == "dry_run":
        consola.print(f"[cyan]Dry-run (no se envio nada).[/cyan] Asunto: {resultado.asunto}")
        consola.print(f"Destino: {config.email.to_address or '(sin configurar)'}")
        for shortcode in resultado.shortcodes:
            consola.print(f"  - {shortcode}")
        if resultado.error:
            consola.print(f"[yellow]Falta para poder enviarlo de verdad:[/yellow] {resultado.error}")
    elif resultado.estado == "sin_novedades":
        consola.print("[yellow]Nada que enviar:[/yellow] no hay elementos nuevos.")
    else:
        consola.print(f"[red]No se envio:[/red] {resultado.detalle}")
        raise typer.Exit(code=1)


@app.command()
def catalogo(
    config_path: Path = typer.Option(None, "--config", help="Ruta a config.yaml"),
    rebuild: bool = typer.Option(
        False, "--rebuild", help="Rehace el catalogo desde los analisis ya guardados"
    ),
    abrir: bool = typer.Option(False, "--abrir", help="Abre el HTML al terminar"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Genera el catalogo interactivo de herramientas (una fila por herramienta).

    Usa --rebuild la primera vez: reconstruye el catalogo con todo lo que ya
    estaba analizado, sin llamar a la IA ni a Instagram.
    """
    import webbrowser
    from datetime import datetime

    config = _preparar(config_path, verbose)
    with Database(config.db_path) as db:
        if rebuild:
            total = db.reconstruir_catalogo()
            consola.print(f"[green]Catalogo reconstruido:[/green] {total} herramientas")

        filas = db.catalogo(dias_nuevo=config.email.catalog_new_days)
        if not filas:
            consola.print(
                "[yellow]El catalogo esta vacio.[/yellow] Corre `instapull catalogo "
                "--rebuild` si ya tenias posts analizados."
            )
            return

        dia = datetime.now().astimezone().strftime("%Y-%m-%d")
        destino = config.output_dir / "catalogo.html"
        destino.write_text(render_catalogo(filas, dia), encoding="utf-8")

    nuevas = sum(1 for f in filas if f["es_nueva"])
    repetidas = sum(1 for f in filas if f["menciones"] > 1)
    consola.print(
        f"[green]Catalogo:[/green] {destino}\n"
        f"{len(filas)} herramientas unicas, {nuevas} nuevas, "
        f"{repetidas} vistas en mas de un post."
    )
    if abrir:
        webbrowser.open(destino.as_uri())


@app.command()
def inventario(
    config_path: Path = typer.Option(None, "--config", help="Ruta a config.yaml"),
    ruta: list[Path] = typer.Option(
        None, "--ruta", help="Carpeta de proyectos a escanear (pisa la config)"
    ),
    sin_dependencias: bool = typer.Option(
        False, "--sin-dependencias", help="Ignora los package.json (menos ruido)"
    ),
    detalle: bool = typer.Option(
        False, "--detalle", help="Lista lo que ya tenes y aparece en el catalogo"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Registra que herramientas YA tenes en tus proyectos del disco.

    Lee skills de `.claude/skills`, servidores de `.mcp.json`, repos clonados y
    dependencias de package.json. El catalogo las marca como "ya la tenes" para
    que no te recomiende algo que ya usas.
    """
    config = _preparar(config_path, verbose)
    raices = [Path(r) for r in (ruta or config.inventory.roots)]
    repos = [] if ruta else [Path(r) for r in config.inventory.repo_roots]

    if not raices and not repos:
        consola.print(
            "[yellow]No hay carpetas que escanear.[/yellow] Agregalas en "
            "`inventory.roots` del config.yaml o pasa --ruta."
        )
        raise typer.Exit(code=1)

    incluir = config.inventory.incluir_dependencias and not sin_dependencias
    hallazgos = escanear(raices, repos, incluir_dependencias=incluir)

    with Database(config.db_path) as db:
        unicas, coinciden = db.registrar_inventario(hallazgos)
        propias = db.inventario_propio()
        filas = db.catalogo(dias_nuevo=config.email.catalog_new_days)

    por_fuente: dict[str, int] = {}
    for datos in propias.values():
        por_fuente[datos["fuente"]] = por_fuente.get(datos["fuente"], 0) + 1

    consola.print(
        f"[green]Inventario:[/green] {unicas} herramientas propias "
        f"({', '.join(f'{v} {k}' for k, v in sorted(por_fuente.items()))})"
    )
    consola.print(
        f"De las {len(filas)} del catalogo, [cyan]{coinciden} ya las tenes[/cyan] "
        f"y {len(filas) - coinciden} son nuevas para vos."
    )

    if detalle:
        tabla = Table(title="Del catalogo, esto ya lo tenes")
        tabla.add_column("Herramienta")
        tabla.add_column("Fuente")
        tabla.add_column("Donde", overflow="fold")
        for fila in filas:
            if fila["ya_tengo"]:
                tabla.add_row(
                    fila["nombre"],
                    fila["fuente_propia"],
                    ", ".join(fila["donde_la_tengo"][:4]),
                )
        consola.print(tabla)


@app.command()
def check(
    config_path: Path = typer.Option(None, "--config", help="Ruta a config.yaml"),
) -> None:
    """Verifica el entorno: ffmpeg, clave de IA, modelo y sesion de Instagram."""
    config = _preparar(config_path, verbose=False)
    tabla = Table(title="Verificacion del entorno")
    tabla.add_column("Componente")
    tabla.add_column("Estado")
    tabla.add_column("Detalle", overflow="fold")
    fallos = 0

    # ffmpeg
    if ffmpeg_disponible():
        tabla.add_row("ffmpeg", "[green]ok[/green]", "disponible en el PATH")
    else:
        fallos += 1
        tabla.add_row(
            "ffmpeg", "[red]falta[/red]", "winget install Gyan.FFmpeg (y abri otra terminal)"
        )

    # Clave y modelo de IA
    cliente = _cliente_ia(config)
    if cliente is None:
        fallos += 1
        tabla.add_row("OPENROUTER_API_KEY", "[red]falta[/red]", "definila en el entorno")
        tabla.add_row("modelo de IA", "[yellow]sin probar[/yellow]", config.ai.model)
    else:
        tabla.add_row("OPENROUTER_API_KEY", "[green]ok[/green]", "definida")
        try:
            respuesta = cliente.chat(
                [{"role": "user", "content": "Responde solo: ok"}]
            )
            tabla.add_row(
                "modelo de IA",
                "[green]ok[/green]",
                f"{cliente.ultimo_modelo} respondio: {respuesta[:40]}",
            )
        except Exception as exc:  # noqa: BLE001
            fallos += 1
            tabla.add_row("modelo de IA", "[red]error[/red]", str(exc)[:160])

    # Sesion de Instagram
    try:
        session = InstagramSession(config).connect(interactivo=False)
        tabla.add_row("sesion Instagram", "[green]ok[/green]", f"@{session.username}")
        try:
            from .instagram.collection import buscar_coleccion

            buscar_coleccion(session, config.instagram.collection_name)
            tabla.add_row(
                "coleccion",
                "[green]ok[/green]",
                f"'{config.instagram.collection_name}' encontrada",
            )
        except Exception as exc:  # noqa: BLE001
            fallos += 1
            tabla.add_row("coleccion", "[red]error[/red]", str(exc)[:160])
    except InstaPullError as exc:
        fallos += 1
        tabla.add_row("sesion Instagram", "[red]falta[/red]", str(exc)[:160])

    # Correo (solo si el usuario lo activo; no se manda nada aca)
    if config.email.enabled:
        problema = EmailNotifier(
            config.email, config.secrets.resend_api_key
        ).problema_de_configuracion()
        if problema:
            fallos += 1
            tabla.add_row("correo (digest)", "[red]error[/red]", problema)
        else:
            tabla.add_row(
                "correo (digest)",
                "[green]ok[/green]",
                f"{config.email.from_address} -> {config.email.to_address}",
            )
    else:
        tabla.add_row("correo (digest)", "[dim]apagado[/dim]", "email.enabled: false")

    consola.print(tabla)
    if fallos:
        consola.print(f"[red]{fallos} verificacion(es) fallaron.[/red]")
        raise typer.Exit(code=1)
    consola.print("[green]Todo listo. Podes correr `instapull run`.[/green]")


@app.command()
def status(
    config_path: Path = typer.Option(None, "--config", help="Ruta a config.yaml"),
) -> None:
    """Muestra el estado de la base de datos."""
    config = _preparar(config_path, verbose=False)
    with Database(config.db_path) as db:
        datos = db.stats()

    tabla = Table(title=f"InstaPull - coleccion '{config.instagram.collection_name}'")
    tabla.add_column("Metrica")
    tabla.add_column("Valor", justify="right")
    for clave, valor in datos.items():
        tabla.add_row(clave.replace("_", " "), str(valor))
    consola.print(tabla)
    consola.print(f"Base de datos: {config.db_path}")
    consola.print(
        f"Modelo de IA:  {config.ai.model} (fallback: {config.ai.model_fallback})"
    )


if __name__ == "__main__":
    app()
