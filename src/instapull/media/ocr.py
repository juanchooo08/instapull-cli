"""OCR sobre fotogramas e imagenes, para capturar nombres, repos y enlaces.

Usa rapidocr-onnxruntime: corre local en CPU y no exige instalar Tesseract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from ..logging_setup import get_logger

log = get_logger(__name__)

_motor: Any = None
_motor_fallido = False


def _cargar_motor() -> Any | None:
    global _motor, _motor_fallido
    if _motor is not None or _motor_fallido:
        return _motor
    try:
        from rapidocr_onnxruntime import RapidOCR

        _motor = RapidOCR()
        log.info("ocr_listo")
    except Exception as exc:  # noqa: BLE001
        _motor_fallido = True
        log.warning("ocr_no_disponible", error=str(exc)[:200])
    return _motor


def ocr_imagen(ruta: Path) -> str:
    """Texto detectado en una imagen, o cadena vacia."""
    motor = _cargar_motor()
    if motor is None or not ruta.exists():
        return ""
    try:
        resultado, _tiempos = motor(str(ruta))
    except Exception as exc:  # noqa: BLE001
        log.debug("ocr_fallo", archivo=str(ruta), error=str(exc)[:200])
        return ""
    if not resultado:
        return ""
    lineas = [str(fila[1]).strip() for fila in resultado if len(fila) > 1]
    return "\n".join(l for l in lineas if l)


def ocr_de_imagenes(rutas: Iterable[Path], activo: bool = True) -> str:
    """OCR de varias imagenes, deduplicando lineas repetidas entre fotogramas."""
    if not activo:
        return ""
    vistas: set[str] = set()
    salida: list[str] = []
    for ruta in rutas:
        for linea in ocr_imagen(ruta).splitlines():
            limpia = linea.strip()
            if len(limpia) < 3:
                continue
            clave = limpia.lower()
            if clave in vistas:
                continue
            vistas.add(clave)
            salida.append(limpia)
    texto = "\n".join(salida)
    if texto:
        log.info("ocr_completado", lineas=len(salida))
    return texto
