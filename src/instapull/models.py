"""Modelos de dominio compartidos por toda la aplicacion."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def utcnow_iso() -> str:
    """Marca de tiempo actual en ISO-8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    CAROUSEL = "carousel"
    UNKNOWN = "unknown"


class ItemStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADED = "downloaded"
    ANALYZED = "analyzed"
    ERROR = "error"


class Categoria(str, Enum):
    HERRAMIENTA_IA = "herramienta de IA"
    REPO_GITHUB = "repo de GitHub"
    TUTORIAL = "tutorial"
    PRODUCTO_NEGOCIO = "producto o negocio"
    OTRO = "otro"


class SavedItem(BaseModel):
    """Un post o reel de la coleccion, tal como viene de Instagram."""

    shortcode: str
    media_id: str = ""
    author: str = ""
    taken_at: str = ""
    caption: str = ""
    permalink: str = ""
    media_type: MediaType = MediaType.UNKNOWN
    media_dir: str = ""
    media_files: list[str] = Field(default_factory=list)
    video_duration: float | None = None
    status: ItemStatus = ItemStatus.PENDING
    error: str | None = None


class KeywordDetection(BaseModel):
    """Resultado de buscar la consigna 'comenta X' en un caption."""

    pide_comentario: bool = False
    palabra: str | None = None
    # 'regex' o 'ia': de donde salio la deteccion
    fuente: str = "regex"
    confianza: float = 0.0

    @field_validator("palabra")
    @classmethod
    def _limpiar_palabra(cls, v: str | None) -> str | None:
        if v is None:
            return None
        limpia = v.strip().strip("\"'“”‘’¡!¿?.,;:").strip()
        return limpia or None


class PostRequisitos(BaseModel):
    """Que exige un post para soltar su recurso, y por que via conviene ir.

    `via` decide el gasto: 'directa' significa que el enlace ya esta en el post
    y no hay que interactuar con nadie. Solo cuando no hay via directa se
    consideran las acciones publicas (comentar, seguir, like).
    """

    # directa | comentario | ninguna
    via: str = "ninguna"
    # comentar | seguir | like | guardar | etiquetar
    requisitos: list[str] = Field(default_factory=list)
    palabra: str | None = None
    urls_directas: list[str] = Field(default_factory=list)
    cumplidos: list[str] = Field(default_factory=list)

    @property
    def exige(self) -> bool:
        return bool(self.requisitos)

    def pide(self, requisito: str) -> bool:
        return requisito in self.requisitos


class ResolvedLink(BaseModel):
    """Un enlace ya expandido, con el contenido de su destino."""

    url_original: str
    url_final: str = ""
    titulo: str = ""
    # github_repo | herramienta | doc | video | otro | error
    tipo: str = "otro"
    extracto: str = ""
    error: str | None = None


class DmResult(BaseModel):
    """Lo que devolvio el flujo de comentario -> DM para un post."""

    # not_attempted | commented | received | timeout | blocked | error
    estado: str = "not_attempted"
    keyword: str | None = None
    comment_id: str | None = None
    commented_at: str | None = None
    dm_received_at: str | None = None
    dm_text: str = ""
    dm_links: list[str] = Field(default_factory=list)
    turnos: int = 0
    error: str | None = None


class MediaContext(BaseModel):
    """Todo lo que se extrajo localmente del medio antes de llamar al modelo."""

    frames: list[str] = Field(default_factory=list)
    transcript: str = ""
    ocr_text: str = ""
    duration: float | None = None


class Analysis(BaseModel):
    """Salida estructurada del modelo de IA, en espanol."""

    titulo: str = ""
    resumen: str = ""
    categoria: Categoria = Categoria.OTRO
    herramientas: list[str] = Field(default_factory=list)
    repos: list[str] = Field(default_factory=list)
    enlaces: list[str] = Field(default_factory=list)
    valoracion: int = 1
    etiquetas: list[str] = Field(default_factory=list)
    modelo: str = ""
    tokens: int = 0

    @field_validator("valoracion", mode="before")
    @classmethod
    def _acotar_valoracion(cls, v: Any) -> int:
        try:
            n = int(round(float(v)))
        except (TypeError, ValueError):
            return 1
        return max(1, min(5, n))

    @field_validator("categoria", mode="before")
    @classmethod
    def _normalizar_categoria(cls, v: Any) -> Any:
        if not isinstance(v, str):
            return v
        texto = v.strip().lower()
        equivalencias = {
            "herramienta de ia": Categoria.HERRAMIENTA_IA,
            "herramienta ia": Categoria.HERRAMIENTA_IA,
            "ai tool": Categoria.HERRAMIENTA_IA,
            "repo de github": Categoria.REPO_GITHUB,
            "repo github": Categoria.REPO_GITHUB,
            "github repo": Categoria.REPO_GITHUB,
            "repositorio": Categoria.REPO_GITHUB,
            "tutorial": Categoria.TUTORIAL,
            "producto o negocio": Categoria.PRODUCTO_NEGOCIO,
            "producto": Categoria.PRODUCTO_NEGOCIO,
            "negocio": Categoria.PRODUCTO_NEGOCIO,
            "otro": Categoria.OTRO,
        }
        return equivalencias.get(texto, Categoria.OTRO)

    @field_validator("herramientas", "repos", "enlaces", "etiquetas", mode="before")
    @classmethod
    def _normalizar_listas(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        if isinstance(v, list):
            salida: list[str] = []
            for elem in v:
                if isinstance(elem, str) and elem.strip():
                    salida.append(elem.strip())
                elif isinstance(elem, dict):
                    # El modelo a veces devuelve [{"nombre": "..."}]
                    for clave in ("nombre", "name", "url", "titulo"):
                        if isinstance(elem.get(clave), str):
                            salida.append(elem[clave].strip())
                            break
            return salida
        return []


class ProcessedItem(BaseModel):
    """Un elemento con todo su procesamiento, listo para persistir o reportar."""

    item: SavedItem
    analysis: Analysis | None = None
    dm: DmResult = Field(default_factory=DmResult)
    links: list[ResolvedLink] = Field(default_factory=list)
    media: MediaContext = Field(default_factory=MediaContext)
    requisitos: PostRequisitos = Field(default_factory=PostRequisitos)
    # Nombres que ya estaban en el catalogo antes de este post
    herramientas_repetidas: list[str] = Field(default_factory=list)
