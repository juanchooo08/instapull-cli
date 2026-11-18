# InstaPull

> **¿Primera vez acá y no sos programador?** No leas este manual: abrí
> [EMPEZAR-AQUI.md](EMPEZAR-AQUI.md). Claude Code se encarga de instalarlo y configurarlo
> todo siguiendo [CLAUDE.md](CLAUDE.md).

Extrae, resuelve y analiza los posts y reels guardados en una colección de Instagram
(por defecto la colección **"AI"**) y genera un informe estructurado en español de cada
elemento: título, resumen, categoría, herramientas, repos, enlaces, valoración 1-5 y etiquetas.

Resuelve además el patrón más molesto de estas cuentas: los posts tipo ManyChat que dicen
*"comentá X y te mando el link por DM"*. La herramienta detecta la palabra, comenta, espera
el mensaje directo, sigue los enlaces hasta su destino final y suma ese contenido al análisis.

---

## Índice

1. [Requisitos](#1-requisitos)
2. [Instalación paso a paso (Windows / PowerShell)](#2-instalación-paso-a-paso-windows--powershell)
3. [Variables de entorno](#3-variables-de-entorno)
4. [Primer login](#4-primer-login)
5. [Verificar que todo está listo](#5-verificar-que-todo-está-listo)
6. [Uso](#6-uso)
7. [Configuración](#7-configuración)
8. [Qué genera y dónde](#8-qué-genera-y-dónde)
9. [Módulo de comentario y DM](#9-módulo-de-comentario-y-dm)
10. [Costos del modelo de IA](#10-costos-del-modelo-de-ia)
11. [Tests](#11-tests)
12. [Solución de problemas](#12-solución-de-problemas)
13. [Resumen diario por correo](#13-resumen-diario-por-correo)
14. [Videos de YouTube](#14-videos-de-youtube)

---

## 1. Requisitos

| Componente | Versión | Por qué |
|---|---|---|
| **Python 3.12** (o 3.13) | 3.12.x | `faster-whisper` depende de `ctranslate2`, que **no publica wheels para Python 3.14**. Con 3.14 la instalación falla. |
| **ffmpeg** | cualquiera reciente | Extrae fotogramas y audio de los reels. |
| Clave de **OpenRouter** | — | Para el modelo de visión que analiza el contenido. |
| Cuenta de Instagram | — | La que tiene la colección guardada. |

---

## 2. Instalación paso a paso (Windows / PowerShell)

Abrí **PowerShell** y ejecutá los comandos en orden.

### Paso 1 — Instalar Python 3.12 y ffmpeg

```powershell
winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
```

> Con Chocolatey, en su lugar: `choco install python312 ffmpeg -y`

**Cerrá PowerShell y abrí una ventana nueva** (winget modifica el PATH y los cambios solo
aplican a terminales nuevas). Verificá:

```powershell
ffmpeg -version
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" --version
```

Deberías ver `ffmpeg version ...` y `Python 3.12.x`.

### Paso 2 — Ir al proyecto y crear el entorno virtual

```powershell
cd "C:\PROYECTOS SAAS\InstaPull\instapull"
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Si PowerShell bloquea el script de activación:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Con el entorno activo el prompt muestra `(.venv)`.

### Paso 3 — Instalar las dependencias

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

La primera vez descarga alrededor de 500 MB (onnxruntime, ctranslate2, opencv). Tarda unos
minutos. El modelo de whisper (~500 MB) se descarga solo la primera vez que analices un video.

---

## 3. Variables de entorno

Los secretos **nunca** se escriben en el código ni en `config.yaml`.

**Opción A — persistentes** (recomendada; hay que abrir una terminal nueva después):

```powershell
setx OPENROUTER_API_KEY "sk-or-v1-tu-clave-aca"
setx IG_USERNAME "tu_usuario_de_instagram"
setx IG_PASSWORD "tu_contrasena"
```

**Opción B — solo para la sesión actual:**

```powershell
$env:OPENROUTER_API_KEY = "sk-or-v1-tu-clave-aca"
$env:IG_USERNAME = "tu_usuario_de_instagram"
$env:IG_PASSWORD = "tu_contrasena"
```

**Opción C — archivo `.env`** (queda fuera de git):

```powershell
Copy-Item .env.example .env
notepad .env
```

`IG_USERNAME` e `IG_PASSWORD` son opcionales: si no están, se piden por consola en el
primer login y la contraseña no se guarda en ningún lado.

`RESEND_API_KEY` solo hace falta si activás el resumen diario por correo
(ver [sección 13](#13-resumen-diario-por-correo)).

---

## 4. Primer login

```powershell
instapull login
```

Qué esperar:

- Si Instagram pide **verificación en dos pasos**, la herramienta se detiene y te pide el
  código por consola. Ingresalo y sigue sola.
- Si Instagram pide un **checkpoint** ("confirmá que sos vos"), vas a ver un mensaje que te
  indica abrir la app o instagram.com con esa cuenta, aprobar el acceso, y volver a correr
  `instapull login`.
- Al terminar, la sesión queda guardada en `data\session\instaloader.session` y se reutiliza
  en todas las corridas siguientes. **No hace falta volver a loguearse** salvo que la sesión
  expire, y en ese caso el mensaje te lo dice explícitamente.

---

## 5. Verificar que todo está listo

```powershell
instapull check
```

Verifica en un solo paso: ffmpeg en el PATH, la clave de OpenRouter, que el modelo responde
de verdad, que la sesión de Instagram es válida y que **existe la colección "AI"**. Si algo
falla, muestra exactamente qué y cómo arreglarlo.

---

## 6. Uso

### Primero, siempre, en seco

```powershell
instapull run --dry-run --limit 10
```

Lista los elementos que procesaría, y en cuáles comentaría y con qué palabra. **No descarga,
no comenta, no gasta tokens, no escribe nada.**

### Corrida normal (sin comentar)

```powershell
instapull run --limit 5
```

Descarga, analiza y persiste. Al terminar genera los tres informes.

### Corrida completa, con el módulo de comentario y DM

```powershell
instapull run --limit 10 --enable-comments --max-comments 3
```

Requiere además poner `comments.enabled: true` en `config.yaml`. Es un doble interruptor a
propósito: nada comenta por accidente.

### Otros comandos

```powershell
instapull run --force --limit 10   # reprocesa elementos ya analizados
instapull report                   # regenera los informes desde la base de datos
instapull digest --dry-run --force # muestra el correo que se enviaria, sin enviarlo
instapull digest                   # envia el resumen diario por correo
instapull status                   # resumen de lo que hay en la base
instapull run -v                   # logs detallados
instapull --help                   # ayuda de todos los comandos
```

También funciona sin activar el entorno: `.\.venv\Scripts\python.exe -m instapull run`

### Modo incremental

Por defecto **nunca** re-descarga ni re-analiza lo ya registrado. Podés correr la herramienta
todos los días: solo procesa lo nuevo. `--force` reprocesa todo.

---

## 7. Configuración

Todo se edita en `config.yaml`:

| Clave | Qué controla | Por defecto |
|---|---|---|
| `instagram.collection_name` | Nombre de la colección a recorrer | `"AI"` |
| `instagram.max_items_per_run` | Tope de elementos por corrida | `50` |
| `instagram.request_delay_seconds` | Pausa aleatoria entre peticiones | `[4, 12]` |
| `ai.model` / `ai.model_fallback` | Modelo de visión y su respaldo | `qwen/qwen3.7-flash` / `google/gemini-3.7-flash` |
| `media.frame_interval_seconds` | Un fotograma cada N segundos | `3` |
| `media.max_frames_per_video` | Tope de fotogramas enviados al modelo | `12` |
| `media.whisper_model` | Modelo de transcripción (CPU) | `small` |
| `comments.enabled` | Interruptor maestro del módulo de comentarios | `false` |
| `comments.max_comments_per_run` | Tope de comentarios por corrida | `5` |
| `comments.action_delay_seconds` | Pausa entre acciones de escritura | `[60, 180]` |
| `comments.dm_wait_max_seconds` | Espera máxima del DM | `600` (10 min) |
| `output.language` | Idioma de la salida | `es` |
| `email.enabled` | Interruptor maestro del resumen por correo | `false` |
| `email.from_address` / `email.to_address` | Remitente verificado en Resend y destinatario | `""` |
| `email.send_hour` | Hora local a partir de la cual se envía | `9` |
| `email.max_items` | Tope de elementos por correo | `25` |

Cambiar de modelo de IA es editar una sola línea: el cliente habla el formato OpenAI contra
OpenRouter, así que cualquier modelo del catálogo funciona sin tocar código.

---

## 8. Qué genera y dónde

```
instapull/
├── output/
│   ├── informe.md      # informe agrupado por categoría, ordenado por valoración
│   ├── items.json      # exportación completa
│   └── items.csv       # una fila por elemento (abre directo en Excel)
├── data/
│   ├── instapull.db    # base SQLite: items, análisis, comentarios, enlaces, corridas, envíos de correo
│   ├── media/<shortcode>/   # imágenes, video, fotogramas y audio de cada elemento
│   └── session/        # sesión de Instagram
└── logs/
    └── instapull.log   # log rotativo
```

Cada elemento del informe incluye: título corto, resumen de 2-3 frases, categoría
(herramienta de IA / repo de GitHub / tutorial / producto o negocio / otro), herramientas,
repos, enlaces (marcando los obtenidos por DM), valoración 1-5 de qué tan aprovechable es
para construir o vender algo, y etiquetas libres.

---

## 9. Módulo de comentario y DM

Cómo funciona, paso a paso:

1. **Detecta la consigna** en el caption con tres capas de regex (palabra entre comillas,
   palabra en MAYÚSCULAS, palabra suelta con promesa de DM). Si ninguna alcanza, le pregunta
   al modelo de IA.
2. **Comenta** esa palabra exacta con tu cuenta.
3. **Espera el DM** sondeando el inbox con intervalos crecientes (30 s → 60 s → 120 s), hasta
   10 minutos por defecto. Busca en la bandeja normal **y en "solicitudes de mensaje"**: si la
   cuenta no te sigue, su DM cae ahí y la solicitud se acepta automáticamente para poder leerla.
4. Si el bot **pide una respuesta** para continuar, el modelo decide qué contestar (hasta
   3 turnos) hasta llegar al enlace.
5. **Extrae todos los enlaces**, sigue las redirecciones (bit.ly, ManyChat, Linktree) hasta la
   URL final y guarda el contenido de destino. En repos de GitHub lee el README.
6. **Si el DM llega tarde** (después de los 10 minutos), no se pierde: al inicio de cada
   corrida se revisan los posts comentados que todavía no tienen enlace, y si el mensaje ya
   llegó se recupera y **se rehace el análisis** con ese contenido. Ese paso solo lee, nunca
   comenta, así que corre siempre.

### Límites de seguridad

- Detrás de **dos** interruptores: `--enable-comments` **y** `comments.enabled: true`.
- Máximo de comentarios por corrida (5 por defecto), configurable con `--max-comments`.
- Pausa aleatoria de **60 a 180 segundos** entre acciones de escritura.
- **Detención inmediata** de toda la corrida ante cualquier señal de acción bloqueada,
  checkpoint o rate limit, guardando el progreso.
- La tabla `comment_actions` tiene el shortcode como clave primaria: **es imposible comentar
  dos veces el mismo post**, incluso entre corridas distintas.

> Comentar y mandar DMs automáticamente va contra los términos de uso de Instagram. El módulo
> está apagado por defecto y con topes conservadores por ese motivo. Usalo con criterio y
> preferentemente con una cuenta secundaria.

---

## 10. Costos del modelo de IA

Base: ~7.000 tokens de entrada por elemento (6 fotogramas + caption + transcripción + DM) y
~600 de salida.

| Modelo | $/M entrada | $/M salida | Costo por 100 posts |
|---|---|---|---|
| **qwen/qwen3.7-flash** (primario) | $0,03 | $0,13 | **~$0,03** |
| **google/gemini-3.7-flash** (respaldo) | $0,375 | $1,875 | ~$0,37 |

El fallback solo se usa cuando el primario devuelve 429/5xx o un JSON que no valida.

---

## 11. Tests

```powershell
pytest
```

80 pruebas que cubren: detección de la palabra clave en captions reales (incluyendo falsos
positivos como "comentá qué te pareció"), validación y normalización de la respuesta del
modelo, persistencia e idempotencia, blindaje de no comentar dos veces y de los topes por
corrida, detención ante acción bloqueada, lectura de DMs (bandeja normal, solicitudes de
mensaje y recuperación tardía), paginación de la colección, extracción/resolución de
enlaces con HTTP simulado, y el resumen por correo (render y escapado del HTML, respuesta
y rechazo de Resend, tope de elementos, ventana de envío diario, y que un elemento ya
notificado nunca se repita).

---

## 12. Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| `ERROR: Could not find a version that satisfies the requirement ctranslate2` | Estás usando Python 3.14 | Creá el venv con Python 3.12 (paso 2) |
| `no encuentro ffmpeg` | PATH desactualizado | Cerrá y abrí PowerShell. Si sigue, reinstalá con winget |
| `No hay una sesion valida` | Sesión expirada o inexistente | `instapull login` |
| `No encontre la coleccion 'AI'` | El nombre no coincide exactamente | El mensaje lista tus colecciones; copiá el nombre exacto a `config.yaml` |
| `Falta OPENROUTER_API_KEY` | Variable no definida en esta terminal | Definila (sección 3) y abrí una terminal nueva si usaste `setx` |
| `Corrida detenida: accion bloqueada` | Instagram limitó la cuenta | Esperá 24-48 h, bajá `max_comments_per_run` y subí las pausas. El progreso quedó guardado |
| `Corrida detenida: limite de peticiones` | Demasiadas peticiones | Esperá y volvé a correr: el modo incremental retoma donde quedó |
| Instagram pide un código repetidamente | Checkpoint sin resolver | Abrí la app, aprobá el acceso y volvé a correr `instapull login` |
| La transcripción sale vacía | El video no tiene voz | Es correcto: el análisis sigue con fotogramas, OCR y caption |
| Comenté pero el DM nunca apareció en el informe | El bot tardó más que el timeout | Volvé a correr `instapull run`: el primer paso recupera los DM tardíos y rehace ese análisis |
| `No se envio: falta RESEND_API_KEY` | Variable no definida en esta terminal | Definila (sección 3) y abrí una terminal nueva si usaste `setx` |
| `Resend respondio 403/422` | Dominio o remitente sin verificar en Resend | Verificá el dominio en el panel de Resend y revisá `email.from_address` |
| `No se envia: ya se envio hoy` | Ya salió el digest del día | Es correcto. `--force` lo manda igual |
| El correo llegó vacío o con menos elementos | Los demás ya se habían notificado antes | Es correcto: cada elemento sale una sola vez. `instapull status` muestra el total notificado |

Los logs completos están en `logs\instapull.log`. Para verlos en vivo:
`Get-Content logs\instapull.log -Wait`

---

## 13. Resumen diario por correo

`instapull digest` manda por correo los elementos **nuevos desde el último envío**, agrupados
por categoría y ordenados por valoración. Está apagado por defecto.

### Configurarlo

1. Creá una cuenta en [resend.com](https://resend.com) y verificá un dominio (o usá el
   remitente de prueba que te da Resend).
2. Poné la clave en el entorno:

   ```powershell
   setx RESEND_API_KEY "re_tu_clave_aca"
   ```

3. Completá el bloque `email:` de `config.yaml`:

   ```yaml
   email:
     enabled: true
     from_address: "InstaPull <avisos@tudominio.com>"
     to_address: "vos@tucorreo.com"
     send_hour: 9
     max_items: 25
   ```

4. Verificá sin mandar nada:

   ```powershell
   instapull digest --dry-run --force
   ```

   Lista el asunto, el destino y qué elementos entrarían. Si falta algo para poder enviar
   de verdad, te lo dice ahí mismo.

`instapull check` también muestra el estado del correo cuando está activado.

### Uso

```powershell
instapull digest              # envia si corresponde (hora + una vez por dia)
instapull digest --force      # ignora la hora y el envio del dia
instapull digest --limit 10   # tope de elementos de este correo
instapull digest --dry-run    # no manda nada
```

Sin `--force`, el comando solo envía si ya pasó `send_hour` y todavía no se mandó nada hoy.
Eso permite programarlo cada pocas horas sin duplicar correos. En Windows, con el Programador
de tareas, apuntando a:

```
C:\PROYECTOS SAAS\InstaPull\instapull\.venv\Scripts\instapull.exe digest
```

### Qué garantiza

- **Nunca repite un elemento**: la tabla `email_sends` tiene el shortcode como clave primaria,
  así que lo ya notificado no vuelve a salir en otro correo.
- **Un fallo de red no pierde elementos**: solo se marcan como notificados si Resend aceptó
  el envío. Si falla, el digest siguiente los vuelve a incluir y el error queda registrado
  en `email_digests`.
- **Nada de HTML inyectado**: todo lo que viene de Instagram (títulos, resúmenes, etiquetas)
  se escapa antes de armar el correo.
- **Correos acotados**: `max_items` limita cuántos elementos entran; el resto espera al
  digest siguiente.
- El correo va en HTML con estilos en línea (se ve igual en Gmail y Outlook) y con una
  versión en texto plano de respaldo.

---

## 14. Videos de YouTube

La misma cadena de análisis, con una playlist propia de YouTube en lugar de la colección de
guardados. No usa la sesión de Instagram y no hace ninguna acción pública.

Requiere `yt-dlp` (viene en `requirements.txt`) y ffmpeg.

### Configurarlo

En `config.yaml`:

```yaml
youtube:
  playlist_url: "https://www.youtube.com/playlist?list=..."
  max_items_per_run: 10
  max_duration_minutes: 40   # los videos más largos se saltean
  max_height: 480            # para leer pantallas alcanza
  prefer_subs: true          # subtítulos antes que whisper
  sub_langs: ["es", "en"]
  frame_interval_seconds: 30 # un fotograma cada 30 s
  max_frames_per_video: 12
  download_timeout_seconds: 900
```

La playlist puede ser pública o **no listada**. Las privadas no se pueden leer sin cookies
de YouTube.

### Uso

```powershell
instapull youtube --dry-run            # qué videos agarraría, sin bajar nada
instapull youtube --limit 5            # procesa 5 videos nuevos
instapull youtube --playlist <url>     # una playlist distinta, sin tocar el config
instapull youtube --force              # reprocesa lo ya analizado
```

### Qué hace con cada video

1. Lista la playlist con `yt-dlp --flat-playlist` (una sola petición, nada descargado).
2. Saltea lo ya analizado y lo que pasa de `max_duration_minutes`.
3. Baja el video a `data/media/yt_<video_id>/`, con su `info.json` y su portada.
4. Pide los subtítulos en una llamada aparte. Si YouTube los niega (429 es común), el video
   ya está bajado y se transcribe con whisper.
5. Saca fotogramas con ffmpeg, les pasa OCR, resuelve los enlaces de la descripción y manda
   todo al modelo.
6. Guarda el análisis con el id `yt:<video_id>`, que nunca choca con un shortcode de
   Instagram, y lo suma al **mismo** catálogo: una herramienta vista en un reel y en un
   video de YouTube queda como una sola entrada con dos menciones.
