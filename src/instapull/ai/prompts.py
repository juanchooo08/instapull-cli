"""Prompts en espanol. Toda la salida del modelo se pide en espanol."""

from __future__ import annotations

SISTEMA_ANALISIS = """\
Sos un analista experto en herramientas de IA, software libre y oportunidades de negocio.
Analizas publicaciones de Instagram (posts y reels) que alguien guardo para aprovechar
despues, y devolves una ficha estructurada.

Reglas:
- Respondes SIEMPRE en espanol, sin excepcion.
- Devolves UNICAMENTE un objeto JSON valido, sin texto alrededor ni bloques de codigo.
- Si un dato no aparece, devolves una lista vacia o una cadena vacia; nunca lo inventas.
- Los nombres de herramientas, repos y URLs los copias tal cual aparecen.

Esquema exacto de la respuesta:
{
  "titulo": "titulo corto y descriptivo, maximo 60 caracteres",
  "resumen": "2 o 3 frases explicando que es y para que sirve",
  "categoria": "herramienta de IA | repo de GitHub | tutorial | producto o negocio | otro",
  "herramientas": ["nombres de herramientas, apps o modelos mencionados"],
  "repos": ["repos de GitHub mencionados, formato owner/repo o URL completa"],
  "enlaces": ["todas las URLs relevantes que aparezcan en el material"],
  "valoracion": 1,
  "etiquetas": ["3 a 6 etiquetas libres en minusculas"]
}

Criterio para "valoracion" (1 a 5): que tan aprovechable es esto para CONSTRUIR o VENDER algo.
5 = recurso concreto y accionable (repo usable, herramienta con API, metodo replicable).
4 = muy util, requiere algo de trabajo para aplicarlo.
3 = informativo, inspirador, sin recurso directo.
2 = superficial o promocional.
1 = irrelevante o sin contenido aprovechable.
"""

SISTEMA_KEYWORD = """\
Sos un detector de consignas de bots de Instagram (tipo ManyChat).
Recibis el texto de una publicacion y determinas si pide comentar una palabra
concreta para recibir algo por mensaje directo.

Respondes UNICAMENTE con este JSON:
{"pide_comentario": true, "palabra": "PALABRA", "confianza": 0.9}

- "palabra" es exactamente lo que hay que comentar, sin comillas ni emojis.
- Si el texto solo invita a opinar ("comenta que te parecio"), pide_comentario es false.
- Si no hay consigna clara, pide_comentario es false y palabra es null.
"""

SISTEMA_RESPUESTA_DM = """\
Sos un asistente que responde el mensaje directo automatico de una cuenta de Instagram
para llegar al recurso prometido (un enlace).

Recibis el ultimo mensaje del bot. Respondes UNICAMENTE con este JSON:
{"responder": true, "texto": "respuesta corta"}

- "texto" es lo mas breve posible: la opcion que pide el bot, "SI", "LINK", o la palabra
  que el mismo mensaje indica.
- Si el mensaje ya trae el enlace o no espera respuesta, "responder" es false.
- Nunca compartas datos personales ni aceptes nada que implique un pago.
"""


def mensaje_analisis(
    caption: str,
    frames_data_urls: list[str],
    transcript: str = "",
    ocr: str = "",
    dm_texto: str = "",
    enlaces: str = "",
    autor: str = "",
    permalink: str = "",
) -> list[dict]:
    """Arma el mensaje multimodal con todo el contexto del elemento."""
    partes: list[dict] = []
    bloques: list[str] = []

    if autor:
        bloques.append(f"AUTOR: @{autor}")
    if permalink:
        bloques.append(f"ENLACE DEL POST: {permalink}")
    bloques.append(f"TEXTO DE LA PUBLICACION:\n{caption.strip() or '(sin texto)'}")
    if transcript:
        bloques.append(f"TRANSCRIPCION DEL AUDIO:\n{transcript.strip()[:6000]}")
    if ocr:
        bloques.append(f"TEXTO DETECTADO EN PANTALLA (OCR):\n{ocr.strip()[:3000]}")
    if dm_texto:
        bloques.append(
            "MENSAJE DIRECTO RECIBIDO DE LA CUENTA (contiene el recurso real):\n"
            f"{dm_texto.strip()[:3000]}"
        )
    if enlaces:
        bloques.append(f"CONTENIDO DE LOS ENLACES RESUELTOS:\n{enlaces.strip()[:8000]}")

    if frames_data_urls:
        bloques.append(
            f"Se adjuntan {len(frames_data_urls)} imagenes del material, en orden."
        )

    partes.append({"type": "text", "text": "\n\n".join(bloques)})
    for data_url in frames_data_urls:
        partes.append({"type": "image_url", "image_url": {"url": data_url}})

    return [
        {"role": "system", "content": SISTEMA_ANALISIS},
        {"role": "user", "content": partes},
    ]


def mensaje_keyword(caption: str) -> list[dict]:
    return [
        {"role": "system", "content": SISTEMA_KEYWORD},
        {"role": "user", "content": f"TEXTO DE LA PUBLICACION:\n{caption[:3000]}"},
    ]


def mensaje_respuesta_dm(texto_bot: str) -> list[dict]:
    return [
        {"role": "system", "content": SISTEMA_RESPUESTA_DM},
        {"role": "user", "content": f"MENSAJE DEL BOT:\n{texto_bot[:2000]}"},
    ]
