"""Carga de configuracion: config.yaml + variables de entorno.

Los secretos SOLO se leen del entorno (o de un .env local); nunca del YAML.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Raiz del proyecto: .../instapull/
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


class InstagramConfig(BaseModel):
    collection_name: str = "AI"
    max_items_per_run: int = 50
    request_delay_seconds: tuple[float, float] = (4.0, 12.0)
    max_retries: int = 4
    session_file: str = "data/session/instaloader.session"


class AIConfig(BaseModel):
    # "openrouter" (API, pago por token) o "claude-cli" (suscripcion via `claude -p`)
    provider: str = "openrouter"
    claude_model: str = "haiku"
    model: str = "qwen/qwen3.7-flash"
    model_fallback: str = "google/gemini-3.7-flash"
    base_url: str = "https://openrouter.ai/api/v1"
    max_tokens: int = 1500
    temperature: float = 0.2
    max_retries: int = 3
    timeout_seconds: int = 120


class MediaConfig(BaseModel):
    frame_interval_seconds: int = 3
    max_frames_per_video: int = 12
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    ocr_enabled: bool = True
    frame_max_width: int = 1024
    download_media: bool = True


class YouTubeConfig(BaseModel):
    """Fuente YouTube: una playlist propia donde se guardan los videos de IA."""

    playlist_url: str = ""
    max_items_per_run: int = 10
    # Los videos mas largos que esto se saltean (transcribir 2 horas no vale la pena)
    max_duration_minutes: int = 40
    # Altura maxima del video descargado; para leer pantallas 480p alcanza
    max_height: int = 480
    # Si el video trae subtitulos (propios o automaticos) se usan en vez de whisper
    prefer_subs: bool = True
    sub_langs: list[str] = Field(default_factory=lambda: ["es", "en"])
    # Un fotograma cada N segundos: los videos de YouTube son largos
    frame_interval_seconds: int = 30
    max_frames_per_video: int = 12
    download_timeout_seconds: int = 900


class LinksConfig(BaseModel):
    resolve_enabled: bool = True
    timeout_seconds: int = 20
    max_links_per_item: int = 10
    excerpt_chars: int = 2000


class CommentsConfig(BaseModel):
    enabled: bool = False
    max_comments_per_run: int = 5
    action_delay_seconds: tuple[float, float] = (60.0, 180.0)
    dm_wait_max_seconds: int = 600
    dm_poll_intervals: list[int] = Field(default_factory=lambda: [30, 60, 120])
    dm_max_turns: int = 3
    # Seguir al autor cuando el post o su bot condicionan el recurso a seguirlo.
    # Es una accion PUBLICA: el follow queda visible en la cuenta.
    auto_follow: bool = False
    # Dar like cuando el post lo exige. Tambien es PUBLICA.
    auto_like: bool = False
    # Guardar el post cuando lo exige. Es privada: el autor no la ve.
    auto_save: bool = False
    # Saltear el comentario cuando el enlace ya esta en el caption. Con esto en
    # false se comenta igual, aunque no haga falta.
    preferir_via_directa: bool = True


class OutputConfig(BaseModel):
    language: str = "es"
    directory: str = "output"
    data_directory: str = "data"
    database: str = "data/instapull.db"
    log_file: str = "logs/instapull.log"


class EmailConfig(BaseModel):
    """Resumen diario por correo de los elementos nuevos."""

    enabled: bool = False
    provider: str = "resend"
    from_address: str = ""
    to_address: str = ""
    # Hora local a partir de la cual se envia el resumen del dia
    send_hour: int = 9
    # Tope de elementos por correo; el resto queda para el digest siguiente
    max_items: int = 25
    # Adjuntar el catalogo interactivo de herramientas (catalogo.html)
    attach_catalog: bool = True
    # Dias hacia atras que una herramienta se marca como "nueva" en el catalogo
    catalog_new_days: int = 7


class InventoryConfig(BaseModel):
    """Donde buscar lo que el usuario YA tiene, para no recomendarselo."""

    # Carpetas que contienen proyectos (un nivel de subcarpetas)
    roots: list[str] = Field(default_factory=list)
    # Carpetas de repos clonados, agrupados en dos niveles (skills/github/x)
    repo_roots: list[str] = Field(default_factory=list)
    # Las dependencias npm son la fuente mas ruidosa; se pueden apagar
    incluir_dependencias: bool = True


class Secrets(BaseModel):
    openrouter_api_key: str = ""
    ig_username: str = ""
    ig_password: str = ""
    ig_sessionid: str = ""
    resend_api_key: str = ""


class Config(BaseModel):
    instagram: InstagramConfig = Field(default_factory=InstagramConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
    youtube: YouTubeConfig = Field(default_factory=YouTubeConfig)
    links: LinksConfig = Field(default_factory=LinksConfig)
    comments: CommentsConfig = Field(default_factory=CommentsConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    inventory: InventoryConfig = Field(default_factory=InventoryConfig)
    secrets: Secrets = Field(default_factory=Secrets)
    root: Path = PROJECT_ROOT

    # --- rutas absolutas derivadas ------------------------------------

    def path(self, relativa: str) -> Path:
        """Convierte una ruta del config en absoluta respecto de la raiz."""
        p = Path(relativa)
        return p if p.is_absolute() else (self.root / p)

    @property
    def db_path(self) -> Path:
        return self.path(self.output.database)

    @property
    def media_root(self) -> Path:
        return self.path(self.output.data_directory) / "media"

    @property
    def output_dir(self) -> Path:
        return self.path(self.output.directory)

    @property
    def log_path(self) -> Path:
        return self.path(self.output.log_file)

    @property
    def session_path(self) -> Path:
        return self.path(self.instagram.session_file)

    def ensure_dirs(self) -> None:
        """Crea todos los directorios que la aplicacion necesita escribir."""
        for d in (
            self.db_path.parent,
            self.media_root,
            self.output_dir,
            self.log_path.parent,
            self.session_path.parent,
        ):
            d.mkdir(parents=True, exist_ok=True)


def load_config(config_path: Path | str | None = None) -> Config:
    """Lee config.yaml y el entorno, y devuelve la configuracion completa."""
    ruta = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    datos: dict[str, Any] = {}
    if ruta.exists():
        with ruta.open("r", encoding="utf-8") as fh:
            datos = yaml.safe_load(fh) or {}

    # .env local (no obligatorio); las variables ya definidas en el entorno ganan
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    datos["secrets"] = {
        "openrouter_api_key": os.getenv("OPENROUTER_API_KEY", ""),
        "ig_username": os.getenv("IG_USERNAME", ""),
        "ig_password": os.getenv("IG_PASSWORD", ""),
        "ig_sessionid": os.getenv("IG_SESSIONID", ""),
        "resend_api_key": os.getenv("RESEND_API_KEY", ""),
    }
    datos["root"] = ruta.resolve().parent if ruta.exists() else PROJECT_ROOT
    return Config.model_validate(datos)
