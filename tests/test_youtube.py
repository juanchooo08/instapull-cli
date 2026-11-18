"""Fuente YouTube: parseo de la playlist y de los subtitulos."""

from __future__ import annotations

import json

from instapull.models import MediaType
from instapull.youtube import playlist as yt


def test_listar_playlist_parsea_jsonl(monkeypatch):
    lineas = [
        json.dumps(
            {
                "id": "abc12345678",
                "title": "Agentes con Claude",
                "uploader": "Canal IA",
                "duration": 612,
                "url": "https://www.youtube.com/watch?v=abc12345678",
            }
        ),
        "basura que no es json",
        json.dumps({"title": "sin id"}),
    ]
    monkeypatch.setattr(yt, "binario_yt_dlp", lambda: "yt-dlp")
    monkeypatch.setattr(yt, "_correr", lambda args, timeout: "\n".join(lineas))

    items = yt.listar_playlist("https://youtube.com/playlist?list=X", limite=5)

    assert len(items) == 1
    item = items[0]
    assert item.shortcode == "yt:abc12345678"
    assert item.author == "Canal IA"
    assert item.video_duration == 612
    assert item.media_type is MediaType.VIDEO
    assert yt.video_id(item.shortcode) == "abc12345678"


def test_texto_de_vtt_limpia_tiempos_y_etiquetas(tmp_path):
    vtt = tmp_path / "video.es.vtt"
    vtt.write_text(
        "WEBVTT\n"
        "Kind: captions\n"
        "Language: es\n"
        "\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "hola <c>esto</c> es una prueba\n"
        "\n"
        "00:00:03.000 --> 00:00:05.000\n"
        "hola <c>esto</c> es una prueba\n"
        "\n"
        "00:00:05.000 --> 00:00:07.000\n"
        "segunda linea\n",
        encoding="utf-8",
    )

    # Las repeticiones consecutivas de los subtitulos automaticos se colapsan
    assert yt._texto_de_vtt(vtt) == "hola esto es una prueba segunda linea"
