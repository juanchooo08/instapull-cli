"""Persistencia SQLite. Es la fuente de verdad para la idempotencia."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .catalog.normalize import canonicalizar, nombre_legible
from .models import (
    Analysis,
    DmResult,
    ItemStatus,
    MediaType,
    PostRequisitos,
    ProcessedItem,
    ResolvedLink,
    SavedItem,
    utcnow_iso,
)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS items (
    shortcode     TEXT PRIMARY KEY,
    media_id      TEXT,
    author        TEXT,
    taken_at      TEXT,
    caption       TEXT,
    permalink     TEXT,
    media_type    TEXT,
    media_dir     TEXT,
    media_files   TEXT,
    video_duration REAL,
    downloaded_at TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    error         TEXT
);

CREATE TABLE IF NOT EXISTS analyses (
    shortcode    TEXT PRIMARY KEY REFERENCES items(shortcode) ON DELETE CASCADE,
    titulo       TEXT,
    resumen      TEXT,
    categoria    TEXT,
    valoracion   INTEGER,
    herramientas TEXT,
    repos        TEXT,
    enlaces      TEXT,
    etiquetas    TEXT,
    transcript   TEXT,
    ocr_text     TEXT,
    modelo       TEXT,
    tokens       INTEGER,
    created_at   TEXT
);

CREATE TABLE IF NOT EXISTS comment_actions (
    shortcode      TEXT PRIMARY KEY REFERENCES items(shortcode) ON DELETE CASCADE,
    keyword        TEXT,
    comment_id     TEXT,
    commented_at   TEXT,
    dm_status      TEXT,
    dm_received_at TEXT,
    dm_text        TEXT,
    dm_links       TEXT,
    turnos         INTEGER DEFAULT 0,
    error          TEXT
);

CREATE TABLE IF NOT EXISTS resolved_links (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    shortcode     TEXT REFERENCES items(shortcode) ON DELETE CASCADE,
    url_original  TEXT,
    url_final     TEXT,
    titulo        TEXT,
    tipo          TEXT,
    extracto      TEXT,
    error         TEXT,
    UNIQUE(shortcode, url_original)
);

CREATE TABLE IF NOT EXISTS runs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at            TEXT,
    finished_at           TEXT,
    procesados            INTEGER DEFAULT 0,
    errores               INTEGER DEFAULT 0,
    comentarios_publicados INTEGER DEFAULT 0,
    nota                  TEXT
);

CREATE TABLE IF NOT EXISTS email_digests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at    TEXT,
    elementos  INTEGER DEFAULT 0,
    asunto     TEXT,
    message_id TEXT,
    estado     TEXT,
    error      TEXT
);

CREATE TABLE IF NOT EXISTS email_sends (
    shortcode TEXT PRIMARY KEY REFERENCES items(shortcode) ON DELETE CASCADE,
    digest_id INTEGER REFERENCES email_digests(id) ON DELETE CASCADE,
    sent_at   TEXT
);

CREATE TABLE IF NOT EXISTS tools (
    clave             TEXT PRIMARY KEY,
    nombre            TEXT,
    tipo              TEXT,
    categoria         TEXT,
    valoracion_max    INTEGER DEFAULT 0,
    url               TEXT,
    menciones         INTEGER DEFAULT 0,
    primera_shortcode TEXT,
    primera_vez       TEXT,
    ultima_vez        TEXT
);

CREATE TABLE IF NOT EXISTS tool_mentions (
    clave     TEXT REFERENCES tools(clave) ON DELETE CASCADE,
    shortcode TEXT REFERENCES items(shortcode) ON DELETE CASCADE,
    visto_at  TEXT,
    PRIMARY KEY (clave, shortcode)
);

CREATE TABLE IF NOT EXISTS post_requirements (
    shortcode    TEXT PRIMARY KEY REFERENCES items(shortcode) ON DELETE CASCADE,
    via          TEXT,
    requisitos   TEXT,
    palabra      TEXT,
    cumplidos    TEXT,
    detectado_at TEXT
);

-- Lo que el usuario YA tiene en sus propios proyectos. Comparte la clave
-- canonica con `tools`, asi que el catalogo puede marcar que no hace falta.
CREATE TABLE IF NOT EXISTS owned_tools (
    clave    TEXT PRIMARY KEY,
    nombre   TEXT,
    fuente   TEXT,
    origenes TEXT,
    visto_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_analyses_valoracion ON analyses(valoracion);
CREATE INDEX IF NOT EXISTS idx_mentions_shortcode ON tool_mentions(shortcode);
"""


def _json_dump(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False)


def _url_parecida(clave: str, url_de: dict[str, str]) -> str:
    """Enlace del post cuyo dominio corresponde a esa herramienta.

    El nombre y el dominio casi nunca coinciden exactos: "Claude Code" vive en
    claude.ai y "n8n workflows" en n8n.io. Se acepta que uno contenga al otro,
    con un minimo de 4 caracteres para no emparejar por casualidad.
    """
    if len(clave) < 4:
        return ""
    for dominio, url in url_de.items():
        if len(dominio) < 4:
            continue
        if clave.startswith(dominio) or dominio.startswith(clave):
            return url
    return ""


def _json_load(texto: str | None) -> list[str]:
    if not texto:
        return []
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError:
        return []
    return datos if isinstance(datos, list) else []


class Database:
    """Envoltura fina sobre sqlite3 con las operaciones del pipeline."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(ESQUEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # --- items --------------------------------------------------------

    def get_item(self, shortcode: str) -> sqlite3.Row | None:
        cur = self.conn.execute("SELECT * FROM items WHERE shortcode = ?", (shortcode,))
        return cur.fetchone()

    def is_analyzed(self, shortcode: str) -> bool:
        """True si el elemento ya fue analizado (para saltearlo en incremental)."""
        fila = self.get_item(shortcode)
        return bool(fila and fila["status"] == ItemStatus.ANALYZED.value)

    def upsert_item(self, item: SavedItem) -> None:
        self.conn.execute(
            """
            INSERT INTO items (shortcode, media_id, author, taken_at, caption, permalink,
                               media_type, media_dir, media_files, video_duration,
                               downloaded_at, status, error)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(shortcode) DO UPDATE SET
                media_id=excluded.media_id,
                author=excluded.author,
                taken_at=excluded.taken_at,
                caption=excluded.caption,
                permalink=excluded.permalink,
                media_type=excluded.media_type,
                media_dir=excluded.media_dir,
                media_files=excluded.media_files,
                video_duration=excluded.video_duration,
                downloaded_at=excluded.downloaded_at,
                status=excluded.status,
                error=excluded.error
            """,
            (
                item.shortcode,
                item.media_id,
                item.author,
                item.taken_at,
                item.caption,
                item.permalink,
                item.media_type.value,
                item.media_dir,
                _json_dump(item.media_files),
                item.video_duration,
                utcnow_iso(),
                item.status.value,
                item.error,
            ),
        )
        self.conn.commit()

    def set_status(self, shortcode: str, status: ItemStatus, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE items SET status = ?, error = ? WHERE shortcode = ?",
            (status.value, error, shortcode),
        )
        self.conn.commit()

    # --- analisis -----------------------------------------------------

    def save_analysis(
        self,
        shortcode: str,
        analysis: Analysis,
        transcript: str = "",
        ocr_text: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO analyses (shortcode, titulo, resumen, categoria, valoracion,
                                  herramientas, repos, enlaces, etiquetas,
                                  transcript, ocr_text, modelo, tokens, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(shortcode) DO UPDATE SET
                titulo=excluded.titulo, resumen=excluded.resumen,
                categoria=excluded.categoria, valoracion=excluded.valoracion,
                herramientas=excluded.herramientas, repos=excluded.repos,
                enlaces=excluded.enlaces, etiquetas=excluded.etiquetas,
                transcript=excluded.transcript, ocr_text=excluded.ocr_text,
                modelo=excluded.modelo, tokens=excluded.tokens,
                created_at=excluded.created_at
            """,
            (
                shortcode,
                analysis.titulo,
                analysis.resumen,
                analysis.categoria.value,
                analysis.valoracion,
                _json_dump(analysis.herramientas),
                _json_dump(analysis.repos),
                _json_dump(analysis.enlaces),
                _json_dump(analysis.etiquetas),
                transcript,
                ocr_text,
                analysis.modelo,
                analysis.tokens,
                utcnow_iso(),
            ),
        )
        self.conn.commit()

    # --- comentarios y DM ---------------------------------------------

    def already_commented(self, shortcode: str) -> bool:
        """Blindaje contra comentar dos veces el mismo post."""
        cur = self.conn.execute(
            "SELECT commented_at FROM comment_actions WHERE shortcode = ?", (shortcode,)
        )
        fila = cur.fetchone()
        return bool(fila and fila["commented_at"])

    def save_comment_action(self, shortcode: str, dm: DmResult) -> None:
        self.conn.execute(
            """
            INSERT INTO comment_actions (shortcode, keyword, comment_id, commented_at,
                                         dm_status, dm_received_at, dm_text, dm_links,
                                         turnos, error)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(shortcode) DO UPDATE SET
                keyword=excluded.keyword,
                comment_id=COALESCE(excluded.comment_id, comment_actions.comment_id),
                commented_at=COALESCE(excluded.commented_at, comment_actions.commented_at),
                dm_status=excluded.dm_status, dm_received_at=excluded.dm_received_at,
                dm_text=excluded.dm_text, dm_links=excluded.dm_links,
                turnos=excluded.turnos, error=excluded.error
            """,
            (
                shortcode,
                dm.keyword,
                dm.comment_id,
                dm.commented_at,
                dm.estado,
                dm.dm_received_at,
                dm.dm_text,
                _json_dump(dm.dm_links),
                dm.turnos,
                dm.error,
            ),
        )
        self.conn.commit()

    def get_comment_action(self, shortcode: str) -> DmResult:
        cur = self.conn.execute(
            "SELECT * FROM comment_actions WHERE shortcode = ?", (shortcode,)
        )
        fila = cur.fetchone()
        if not fila:
            return DmResult()
        return DmResult(
            estado=fila["dm_status"] or "not_attempted",
            keyword=fila["keyword"],
            comment_id=fila["comment_id"],
            commented_at=fila["commented_at"],
            dm_received_at=fila["dm_received_at"],
            dm_text=fila["dm_text"] or "",
            dm_links=_json_load(fila["dm_links"]),
            turnos=fila["turnos"] or 0,
            error=fila["error"],
        )

    def pendientes_de_dm(self) -> list[SavedItem]:
        """Posts ya comentados cuyo DM nunca trajo un enlace.

        Son los que hay que volver a mirar al inicio de la corrida siguiente:
        muchos bots contestan despues del tope de espera.
        """
        cur = self.conn.execute(
            """
            SELECT i.* FROM items i
            JOIN comment_actions c ON c.shortcode = i.shortcode
            WHERE c.commented_at IS NOT NULL
              AND (c.dm_status IS NULL OR c.dm_status != 'received')
            ORDER BY c.commented_at DESC
            """
        )
        return [
            SavedItem(
                shortcode=f["shortcode"],
                media_id=f["media_id"] or "",
                author=f["author"] or "",
                taken_at=f["taken_at"] or "",
                caption=f["caption"] or "",
                permalink=f["permalink"] or "",
                media_type=MediaType(f["media_type"] or "unknown"),
                media_dir=f["media_dir"] or "",
                media_files=_json_load(f["media_files"]),
                video_duration=f["video_duration"],
                status=ItemStatus(f["status"]),
                error=f["error"],
            )
            for f in cur.fetchall()
        ]

    # --- enlaces ------------------------------------------------------

    def save_links(self, shortcode: str, links: Iterable[ResolvedLink]) -> None:
        for link in links:
            self.conn.execute(
                """
                INSERT INTO resolved_links (shortcode, url_original, url_final,
                                            titulo, tipo, extracto, error)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(shortcode, url_original) DO UPDATE SET
                    url_final=excluded.url_final, titulo=excluded.titulo,
                    tipo=excluded.tipo, extracto=excluded.extracto, error=excluded.error
                """,
                (
                    shortcode,
                    link.url_original,
                    link.url_final,
                    link.titulo,
                    link.tipo,
                    link.extracto,
                    link.error,
                ),
            )
        self.conn.commit()

    def get_links(self, shortcode: str) -> list[ResolvedLink]:
        cur = self.conn.execute(
            "SELECT * FROM resolved_links WHERE shortcode = ?", (shortcode,)
        )
        return [
            ResolvedLink(
                url_original=f["url_original"],
                url_final=f["url_final"] or "",
                titulo=f["titulo"] or "",
                tipo=f["tipo"] or "otro",
                extracto=f["extracto"] or "",
                error=f["error"],
            )
            for f in cur.fetchall()
        ]

    # --- corridas -----------------------------------------------------

    def start_run(self, nota: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, nota) VALUES (?,?)", (utcnow_iso(), nota)
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def finish_run(
        self, run_id: int, procesados: int, errores: int, comentarios: int
    ) -> None:
        self.conn.execute(
            """UPDATE runs SET finished_at = ?, procesados = ?, errores = ?,
                               comentarios_publicados = ? WHERE id = ?""",
            (utcnow_iso(), procesados, errores, comentarios, run_id),
        )
        self.conn.commit()

    # --- lectura para reportes ----------------------------------------

    def fetch_processed(self) -> list[ProcessedItem]:
        """Todos los elementos analizados, con su analisis, DM y enlaces."""
        cur = self.conn.execute(
            """
            SELECT i.*, a.titulo, a.resumen, a.categoria, a.valoracion, a.herramientas,
                   a.repos, a.enlaces, a.etiquetas, a.modelo, a.tokens
            FROM items i
            JOIN analyses a ON a.shortcode = i.shortcode
            ORDER BY a.valoracion DESC, i.taken_at DESC
            """
        )
        salida: list[ProcessedItem] = []
        for f in cur.fetchall():
            item = SavedItem(
                shortcode=f["shortcode"],
                media_id=f["media_id"] or "",
                author=f["author"] or "",
                taken_at=f["taken_at"] or "",
                caption=f["caption"] or "",
                permalink=f["permalink"] or "",
                media_type=MediaType(f["media_type"] or "unknown"),
                media_dir=f["media_dir"] or "",
                media_files=_json_load(f["media_files"]),
                video_duration=f["video_duration"],
                status=ItemStatus(f["status"]),
                error=f["error"],
            )
            analysis = Analysis(
                titulo=f["titulo"] or "",
                resumen=f["resumen"] or "",
                categoria=f["categoria"] or "otro",
                herramientas=_json_load(f["herramientas"]),
                repos=_json_load(f["repos"]),
                enlaces=_json_load(f["enlaces"]),
                valoracion=f["valoracion"] or 1,
                etiquetas=_json_load(f["etiquetas"]),
                modelo=f["modelo"] or "",
                tokens=f["tokens"] or 0,
            )
            salida.append(
                ProcessedItem(
                    item=item,
                    analysis=analysis,
                    dm=self.get_comment_action(item.shortcode),
                    links=self.get_links(item.shortcode),
                )
            )
        return salida

    # --- digest por correo --------------------------------------------

    def pendientes_de_email(self) -> list[ProcessedItem]:
        """Elementos ya analizados que todavia no salieron en ningun digest."""
        cur = self.conn.execute("SELECT shortcode FROM email_sends")
        ya_enviados = {f["shortcode"] for f in cur.fetchall()}
        return [p for p in self.fetch_processed() if p.item.shortcode not in ya_enviados]

    def ultimo_digest(self) -> sqlite3.Row | None:
        """El ultimo digest enviado con exito (para respetar el envio diario)."""
        cur = self.conn.execute(
            "SELECT * FROM email_digests WHERE estado = 'sent' "
            "ORDER BY sent_at DESC LIMIT 1"
        )
        return cur.fetchone()

    def registrar_digest(
        self,
        shortcodes: Iterable[str],
        asunto: str,
        estado: str,
        message_id: str = "",
        error: str | None = None,
    ) -> int:
        """Guarda el envio y marca sus elementos como ya notificados.

        Los elementos solo se marcan si el envio salio bien: si Resend falla, el
        proximo digest vuelve a incluirlos.
        """
        momento = utcnow_iso()
        lista = list(shortcodes)
        cur = self.conn.execute(
            """INSERT INTO email_digests (sent_at, elementos, asunto, message_id,
                                          estado, error)
               VALUES (?,?,?,?,?,?)""",
            (momento, len(lista), asunto, message_id, estado, error),
        )
        digest_id = int(cur.lastrowid or 0)

        if estado == "sent":
            self.conn.executemany(
                """INSERT INTO email_sends (shortcode, digest_id, sent_at) VALUES (?,?,?)
                   ON CONFLICT(shortcode) DO UPDATE SET
                       digest_id=excluded.digest_id, sent_at=excluded.sent_at""",
                [(s, digest_id, momento) for s in lista],
            )
        self.conn.commit()
        return digest_id

    # --- catalogo de herramientas -------------------------------------

    def herramientas_conocidas(self) -> dict[str, str]:
        """{clave_canonica: nombre} de todo lo ya catalogado.

        Se le pasa al analizador para que no vuelva a describir de cero algo
        que ya esta en el catalogo.
        """
        cur = self.conn.execute("SELECT clave, nombre FROM tools")
        return {f["clave"]: f["nombre"] for f in cur.fetchall()}

    def registrar_herramientas(
        self,
        shortcode: str,
        analysis: Analysis,
        links: Iterable[ResolvedLink] = (),
        momento: str | None = None,
    ) -> tuple[list[str], list[str]]:
        """Suma las herramientas de un analisis al catalogo global.

        La clave canonica es la que decide: "Eleven Labs" y "elevenlabs.io"
        caen en la misma fila. Un post que repite algo ya visto no crea una
        entrada nueva, solo suma una mencion.

        Args:
            momento: cuando se descubrio (ISO-8601 UTC). Por defecto, ahora. Al
                reconstruir el catalogo se pasa la fecha real del analisis, para
                que no aparezca todo el historico como "nuevo".

        Returns:
            (nuevas, repetidas) con los nombres visibles de cada grupo.
        """
        # Enlace representativo por dominio, para poder linkear la herramienta
        url_de: dict[str, str] = {}
        for link in links:
            destino = link.url_final or link.url_original
            clave_url = canonicalizar(destino)
            if clave_url and clave_url not in url_de:
                url_de[clave_url] = destino

        entradas = [("herramienta", n) for n in analysis.herramientas]
        entradas += [("repo", n) for n in analysis.repos]

        momento = momento or utcnow_iso()
        nuevas: list[str] = []
        repetidas: list[str] = []
        vistas_en_este_post: set[str] = set()

        for tipo, bruto in entradas:
            clave = canonicalizar(bruto)
            if not clave or clave in vistas_en_este_post:
                continue
            vistas_en_este_post.add(clave)

            nombre = nombre_legible(bruto)
            url = url_de.get(clave) or _url_parecida(clave, url_de)
            previa = self.conn.execute(
                "SELECT clave, nombre, url FROM tools WHERE clave = ?", (clave,)
            ).fetchone()

            if previa is None:
                self.conn.execute(
                    """INSERT INTO tools (clave, nombre, tipo, categoria,
                                          valoracion_max, url, menciones,
                                          primera_shortcode, primera_vez, ultima_vez)
                       VALUES (?,?,?,?,?,?,0,?,?,?)""",
                    (
                        clave,
                        nombre,
                        tipo,
                        analysis.categoria.value,
                        analysis.valoracion,
                        url,
                        shortcode,
                        momento,
                        momento,
                    ),
                )
                nuevas.append(nombre)
            else:
                # El nombre de la primera aparicion manda: asi el catalogo no
                # cambia de etiqueta cada vez que otro post la escribe distinto.
                self.conn.execute(
                    """UPDATE tools SET
                           ultima_vez = ?,
                           valoracion_max = MAX(valoracion_max, ?),
                           url = CASE WHEN COALESCE(url,'') = '' THEN ? ELSE url END
                       WHERE clave = ?""",
                    (momento, analysis.valoracion, url, clave),
                )
                repetidas.append(previa["nombre"] or nombre)

            self.conn.execute(
                """INSERT INTO tool_mentions (clave, shortcode, visto_at)
                   VALUES (?,?,?) ON CONFLICT(clave, shortcode) DO NOTHING""",
                (clave, shortcode, momento),
            )
            self.conn.execute(
                """UPDATE tools SET menciones =
                       (SELECT COUNT(*) FROM tool_mentions WHERE clave = ?)
                   WHERE clave = ?""",
                (clave, clave),
            )

        self.conn.commit()
        return nuevas, repetidas

    def reconstruir_catalogo(self) -> int:
        """Rehace el catalogo desde los analisis ya guardados.

        Sirve para poblarlo con lo que se proceso antes de que existiera, sin
        volver a llamar al modelo ni a Instagram.
        """
        self.conn.execute("DELETE FROM tool_mentions")
        self.conn.execute("DELETE FROM tools")
        self.conn.commit()

        # Fecha real de cada analisis, para fechar bien la primera aparicion
        analizado_en = {
            f["shortcode"]: f["created_at"]
            for f in self.conn.execute(
                "SELECT shortcode, created_at FROM analyses"
            ).fetchall()
        }
        # De mas viejo a mas nuevo: la primera aparicion tiene que ser la real
        procesados = sorted(
            (p for p in self.fetch_processed() if p.analysis is not None),
            key=lambda p: analizado_en.get(p.item.shortcode) or "",
        )
        for procesado in procesados:
            self.registrar_herramientas(
                procesado.item.shortcode,
                procesado.analysis,
                procesado.links,
                momento=analizado_en.get(procesado.item.shortcode),
            )
        return int(self.conn.execute("SELECT COUNT(*) FROM tools").fetchone()[0])

    def catalogo(self, dias_nuevo: int = 7) -> list[dict[str, Any]]:
        """Una fila por herramienta unica, con los posts donde aparecio."""
        from datetime import datetime, timedelta, timezone

        corte = datetime.now(timezone.utc) - timedelta(days=dias_nuevo)

        cur = self.conn.execute(
            """
            SELECT t.*, m.shortcode, i.author, i.permalink, a.titulo,
                   o.fuente AS propia_fuente, o.origenes AS propios_origenes
            FROM tools t
            LEFT JOIN owned_tools o ON o.clave = t.clave
            LEFT JOIN tool_mentions m ON m.clave = t.clave
            LEFT JOIN items i ON i.shortcode = m.shortcode
            LEFT JOIN analyses a ON a.shortcode = m.shortcode
            ORDER BY t.menciones DESC, t.nombre COLLATE NOCASE
            """
        )

        filas: dict[str, dict[str, Any]] = {}
        for f in cur.fetchall():
            fila = filas.get(f["clave"])
            if fila is None:
                try:
                    primera = datetime.fromisoformat(f["primera_vez"] or "")
                    if primera.tzinfo is None:
                        primera = primera.replace(tzinfo=timezone.utc)
                    es_nueva = primera >= corte
                except ValueError:
                    es_nueva = False
                fila = {
                    "clave": f["clave"],
                    "nombre": f["nombre"] or f["clave"],
                    "tipo": f["tipo"] or "herramienta",
                    "categoria": f["categoria"] or "",
                    "valoracion_max": f["valoracion_max"] or 0,
                    "url": f["url"] or "",
                    "menciones": f["menciones"] or 0,
                    "primera_vez": f["primera_vez"] or "",
                    "ultima_vez": f["ultima_vez"] or "",
                    "es_nueva": es_nueva,
                    # Cruce con lo que el usuario ya tiene en sus proyectos
                    "ya_tengo": bool(f["propia_fuente"]),
                    "fuente_propia": f["propia_fuente"] or "",
                    "donde_la_tengo": json.loads(f["propios_origenes"] or "[]"),
                    "posts": [],
                }
                filas[f["clave"]] = fila
            if f["shortcode"]:
                fila["posts"].append(
                    {
                        "shortcode": f["shortcode"],
                        "autor": f["author"] or "",
                        "titulo": f["titulo"] or "",
                        "permalink": f["permalink"] or "",
                    }
                )
        return list(filas.values())

    # --- lo que el usuario ya tiene -----------------------------------

    def registrar_inventario(
        self, entradas: list[dict[str, str]], reemplazar: bool = True
    ) -> tuple[int, int]:
        """Guarda el inventario propio y dice cuanto del catalogo ya cubre.

        Args:
            entradas: salida de `catalog.inventario.escanear`.
            reemplazar: vacia el inventario previo. Es lo correcto por defecto:
                si el usuario borro un proyecto, esa herramienta ya no la tiene.

        Returns:
            (herramientas propias unicas, cuantas coinciden con el catalogo)
        """
        if reemplazar:
            self.conn.execute("DELETE FROM owned_tools")

        ahora = utcnow_iso()
        # Se agrupa en memoria para que cada herramienta guarde TODOS sus
        # origenes: "Supabase" puede venir de un MCP y de seis package.json.
        agrupado: dict[str, dict[str, Any]] = {}
        for entrada in entradas:
            clave = entrada.get("clave", "")
            if not clave:
                continue
            fila = agrupado.setdefault(
                clave,
                {"nombre": entrada.get("nombre") or clave, "fuentes": set(), "origenes": set()},
            )
            fila["fuentes"].add(entrada.get("fuente", ""))
            if entrada.get("origen"):
                fila["origenes"].add(entrada["origen"])

        # De mas a menos significativa: una skill propia pesa mas que una
        # dependencia npm que quiza entro sola con la plantilla.
        orden = ("skill", "mcp", "repo", "dependencia")
        for clave, fila in agrupado.items():
            fuente = next((f for f in orden if f in fila["fuentes"]), "otra")
            self.conn.execute(
                """INSERT INTO owned_tools (clave, nombre, fuente, origenes, visto_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(clave) DO UPDATE SET
                       nombre = excluded.nombre,
                       fuente = excluded.fuente,
                       origenes = excluded.origenes,
                       visto_at = excluded.visto_at""",
                (
                    clave,
                    fila["nombre"],
                    fuente,
                    json.dumps(sorted(fila["origenes"]), ensure_ascii=False),
                    ahora,
                ),
            )
        self.conn.commit()

        coinciden = self.conn.execute(
            "SELECT COUNT(*) FROM tools t JOIN owned_tools o ON o.clave = t.clave"
        ).fetchone()[0]
        return len(agrupado), coinciden

    def inventario_propio(self) -> dict[str, dict[str, Any]]:
        """Lo ya instalado, por clave canonica."""
        cur = self.conn.execute("SELECT * FROM owned_tools")
        return {
            f["clave"]: {
                "nombre": f["nombre"],
                "fuente": f["fuente"],
                "origenes": json.loads(f["origenes"] or "[]"),
            }
            for f in cur.fetchall()
        }

    # --- requisitos por post ------------------------------------------

    def save_requisitos(self, shortcode: str, req: PostRequisitos) -> None:
        self.conn.execute(
            """INSERT INTO post_requirements (shortcode, via, requisitos, palabra,
                                              cumplidos, detectado_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(shortcode) DO UPDATE SET
                   via=excluded.via, requisitos=excluded.requisitos,
                   palabra=excluded.palabra, cumplidos=excluded.cumplidos,
                   detectado_at=excluded.detectado_at""",
            (
                shortcode,
                req.via,
                _json_dump(req.requisitos),
                req.palabra,
                _json_dump(req.cumplidos),
                utcnow_iso(),
            ),
        )
        self.conn.commit()

    def get_requisitos(self, shortcode: str) -> PostRequisitos:
        f = self.conn.execute(
            "SELECT * FROM post_requirements WHERE shortcode = ?", (shortcode,)
        ).fetchone()
        if not f:
            return PostRequisitos()
        return PostRequisitos(
            via=f["via"] or "ninguna",
            requisitos=_json_load(f["requisitos"]),
            palabra=f["palabra"],
            cumplidos=_json_load(f["cumplidos"]),
        )

    def stats(self) -> dict[str, int]:
        def uno(sql: str) -> int:
            return int(self.conn.execute(sql).fetchone()[0])

        return {
            "elementos": uno("SELECT COUNT(*) FROM items"),
            "analizados": uno("SELECT COUNT(*) FROM items WHERE status = 'analyzed'"),
            "con_error": uno("SELECT COUNT(*) FROM items WHERE status = 'error'"),
            "comentados": uno(
                "SELECT COUNT(*) FROM comment_actions WHERE commented_at IS NOT NULL"
            ),
            "dm_recibidos": uno(
                "SELECT COUNT(*) FROM comment_actions WHERE dm_status = 'received'"
            ),
            "enlaces": uno("SELECT COUNT(*) FROM resolved_links"),
            "corridas": uno("SELECT COUNT(*) FROM runs"),
            "digests_enviados": uno(
                "SELECT COUNT(*) FROM email_digests WHERE estado = 'sent'"
            ),
            "notificados_por_email": uno("SELECT COUNT(*) FROM email_sends"),
        }
