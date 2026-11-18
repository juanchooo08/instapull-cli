# InstaPull — instrucciones para el agente

Este archivo es para ti, Claude Code. **La persona que te habla no es programadora.**
No sabe qué es un entorno virtual, ni una variable de entorno, ni un YAML, y no tiene
por qué saberlo. Tu trabajo es dejar InstaPull funcionando y después correrlo cuando te
lo pidan, hablando en español y en palabras normales.

## Qué es InstaPull

Una herramienta de línea de comandos (Python) que:

1. Lee los posts **guardados** de una cuenta de Instagram (una colección concreta o todos).
2. Baja el video o la imagen de cada uno, le saca fotogramas, lo transcribe y le pasa OCR.
3. Le pide a un modelo de IA que diga **qué herramienta de IA aparece**, para qué sirve,
   qué enlaces trae y cuánto vale la pena (1 a 5).
4. Si el post dice "comentá X y te mando el link", puede comentar y esperar el DM del bot
   para quedarse con el enlace real (módulo opcional, ver abajo).
5. Guarda todo en una base SQLite y genera informes: `output/informe.md`, `items.csv`,
   `items.json` y un catálogo navegable `output/catalogo.html`.
6. Lo mismo con **videos de YouTube** de una playlist propia (`instapull youtube`).

El manual técnico completo es [README.md](README.md). Está escrito para Windows; si la
persona usa Mac, traducí los comandos (`brew` en vez de `winget`, `source .venv/bin/activate`
en vez de `.venv\Scripts\Activate.ps1`).

## Reglas de trato

- **Nunca** le pidas que edite un archivo, que copie comandos ni que "abra el config".
  Los archivos los editás vos con tus herramientas; los comandos los corrés vos.
- Un paso a la vez. Pedile **una sola cosa** por mensaje y esperá.
- Lo único que de verdad tiene que hacer con sus manos es: entrar a Instagram en el
  navegador y copiar una cookie (ver *Paso 4*), y crear la colección de guardados.
- Si algo falla, no le muestres el traceback. Decile en una línea qué pasó y qué vas a
  intentar.
- **Nunca imprimas en el chat el `sessionid`, ni ninguna clave.** Escribilos directo en
  `.env` y confirmá solo "listo, quedó guardado".
- `.env` jamás se sube a git (ya está en `.gitignore`). No lo saques de ahí.

## Instalación (hacelo vos, de arriba a abajo)

### Paso 1 — Detectar el sistema y lo que falta

Averiguá si es Windows o Mac. Después verificá qué hay instalado:

- `python --version` (hace falta **3.12 o 3.13**; 3.14 todavía no sirve, una dependencia
  de la transcripción no tiene paquetes para esa versión)
- `ffmpeg -version` (para sacar fotogramas y audio de los videos)
- `yt-dlp --version` (solo para YouTube; si falta, se instala con pip más abajo)
- `claude --version` (debería estar: te está usando)

Lo que falte, instalalo vos:

- Windows: `winget install Python.Python.3.12` y `winget install Gyan.FFmpeg`
- Mac: `brew install python@3.12 ffmpeg`

Si en Windows `winget` pide confirmación en una ventana, avisale a la persona que le va a
aparecer y que acepte.

### Paso 2 — Entorno e instalación de dependencias

Desde la carpeta del repo:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt    # Windows: .venv\Scripts\pip.exe
.venv/bin/pip install -e .
```

A partir de acá, **siempre** corré los comandos con el Python del entorno
(`.venv/bin/python -m instapull ...`), nunca con el Python del sistema.

### Paso 3 — Configuración

```bash
cp config.example.yaml config.yaml
cp .env.example .env
```

En `config.yaml` dejá:

- `ai.provider: "claude-cli"` — usa la suscripción de Claude de la persona a través del
  binario `claude`. **No hace falta ninguna API key y no se paga nada por token.**
  `ai.claude_model: "haiku"` está bien: es el más rápido y el análisis es sencillo.
- `instagram.collection_name: "AI"` — la colección de guardados a procesar (ver *Paso 5*).
- `email.enabled: false` — el resumen diario por correo queda apagado. Solo encendelo si la
  persona lo pide, y en ese caso necesita una clave propia de [Resend](https://resend.com)
  en `RESEND_API_KEY`.
- `inventory.roots` — carpetas donde tiene sus proyectos, si quiere que el catálogo marque
  lo que ya usa. Si no, dejalo vacío.

En `.env` dejá `OPENROUTER_API_KEY` vacía: con `claude-cli` no se usa.

### Paso 4 — Darle acceso a Instagram (la cookie `sessionid`)

InstaPull puede loguearse con usuario y contraseña (`instapull login`), pero Instagram
manda verificación en dos pasos y a veces bloquea. **El camino corto y más estable es
copiar la cookie de sesión del navegador donde ya está logueada la cuenta.**

Decile, exactamente así, una instrucción por mensaje:

1. "Abrí Chrome y entrá a instagram.com con la cuenta que querés usar."
2. "Apretá F12 (en Mac: Cmd+Option+I). Se abre un panel a un costado."
3. "Arriba de ese panel buscá la pestaña **Application** (o **Aplicación**). Si no la ves,
   está en el `»`."
4. "En la columna izquierda: **Cookies** → **https://www.instagram.com**."
5. "Buscá la fila que dice `sessionid`, hacé doble clic en la columna **Value** y copiala
   completa (Ctrl+C)."
6. "Pegámela acá."

Cuando la pegue:

- Escribila en `.env` como `IG_SESSIONID=<lo que pegó>`.
- **No la repitas en el chat.** Respondé solo "listo".
- Avisale que esa cookie vale mientras no cierre sesión en ese navegador, y que si algún
  día InstaPull dice "sesión expirada", se repite este paso y nada más.
- Decile también que **no cierre sesión** en ese Chrome, porque invalida la cookie.

Consejo que conviene darle: que use una cuenta de Instagram **secundaria** para esto. No es
obligatorio, pero si Instagram llega a marcar actividad automática, el riesgo no cae sobre
su cuenta principal.

### Paso 5 — La colección de guardados

Hay dos formas, y conviene explicarle las dos **con esta recomendación**:

**Recomendada — una colección nueva solo para IA.** En Instagram, cuando guarda un post,
puede mandarlo a una colección. Que cree una llamada exactamente `AI` (mantené
`instagram.collection_name: "AI"` en el config) y de ahí en adelante guarde ahí todo lo de
inteligencia artificial. Ventaja: cada corrida procesa 5 o 10 cosas nuevas, tarda minutos,
y no se mezcla con recetas ni con memes.

Cómo se crea, para que se lo pases con sus palabras: "En Instagram, tocá los tres puntitos
de un post → **Guardar en colección** → **+ Nueva colección** → ponele `AI` → Guardar".

**La otra — procesar todo lo que ya tiene guardado.** Se pone
`instagram.collection_name: "*"` y lee *todos* los guardados, del más nuevo al más viejo.
Sirve para empezar con el archivo histórico. Decile con honestidad lo que implica:

- Son cientos o miles de posts, y cada uno tarda entre 30 segundos y 2 minutos.
- Hay que hacerlo **en tandas**: `--limit 25` por corrida, varias corridas en varios días.
  Instagram corta las sesiones que piden demasiado seguido.
- Va a entrar mucho ruido (todo lo guardado que no sea de IA). El informe lo clasifica
  igual, pero el catálogo queda más sucio.

Lo mejor de los dos mundos, y es lo que le recomendaría: crear la colección `AI` para el
día a día, y aparte vaciar el archivo histórico de a tandas con `--limit`.

### Paso 6 — Verificar

```bash
.venv/bin/python -m instapull check
```

Revisa ffmpeg, el modelo de IA (que responda de verdad), la sesión de Instagram y que la
colección exista. Si algo sale mal, el mensaje dice qué. Arreglalo vos y volvé a correrlo
hasta que esté todo en verde. **No le digas que está listo hasta que `check` pase.**

## Uso diario

Siempre, la primera vez de cada día, en seco:

```bash
.venv/bin/python -m instapull run --dry-run
```

Muestra qué posts procesaría, sin bajar nada ni gastar nada. Mostrale esa tabla.

Corrida normal:

```bash
.venv/bin/python -m instapull run --limit 10
```

Corrida con el módulo de comentario y DM (ver la advertencia de abajo):

```bash
.venv/bin/python -m instapull run --limit 10 --enable-comments
```

Otros:

- `instapull catalogo` → regenera `output/catalogo.html` (el entregable lindo, para abrir
  en el navegador).
- `instapull report` → regenera informe.md / items.csv / items.json.
- `instapull status` → cuántos elementos hay, cuántos analizados, cuántos con error.
- `instapull inventario` → cruza el catálogo con sus proyectos para marcar lo que ya usa.

Es incremental: lo ya analizado se saltea solo. Correrlo dos veces no duplica nada ni
gasta de nuevo.

## Comentarios y DM automáticos (está encendido, explicale qué es)

Muchos posts de IA dicen "comentá *AGENTE* y te mando el link". El módulo comenta esa
palabra, espera el DM del bot del autor y se queda con el enlace real. Si el post exige
seguir a la cuenta o darle like, lo hace (`auto_follow`, `auto_like` en `config.yaml`).

Esto es importante que lo sepa, decíselo tal cual: **son acciones públicas desde su
cuenta.** Los comentarios y los follows los ve cualquiera, y si Instagram detecta
demasiados seguidos puede limitar la cuenta por unas horas o días. Por eso:

- Solo actúa si pasás `--enable-comments`. Sin esa bandera, InstaPull nunca escribe nada.
- Hay topes: 5 comentarios por corrida y 1 a 3 minutos de pausa entre acciones. **No los
  subas**, aunque te lo pida; explicale que el tope es justamente lo que evita el bloqueo.
- Si aparece `accion bloqueada` o `limite de peticiones`, la corrida se detiene sola.
  Esperá **24 horas** antes de volver a correr con `--enable-comments`. Mientras tanto,
  corré sin la bandera: el análisis funciona igual.
- Si prefiere no comentar nunca, poné `comments.enabled: false` en `config.yaml` y listo.

## YouTube

Igual que los guardados de Instagram, pero con una playlist de YouTube. No necesita cookies
ni login.

Pedile que cree una playlist en YouTube (puede ser **no listada**) y que vaya agregando ahí
los videos de IA que quiera analizar: "en un video, botón **Guardar** → **+ Nueva
playlist** → nombre `IA` → privacidad *No listada*". Después que te pase el link de la
playlist (YouTube → Biblioteca → la playlist → copiar la URL del navegador).

Ese link va en `config.yaml`:

```yaml
youtube:
  playlist_url: "https://www.youtube.com/playlist?list=..."
```

Y se corre:

```bash
.venv/bin/python -m instapull youtube --dry-run      # qué videos agarraría
.venv/bin/python -m instapull youtube --limit 5      # procesa de verdad
```

Detalles que conviene saber:

- Si el video tiene subtítulos (propios o automáticos), se usan y es rápido. Si no, se
  transcribe con whisper en la máquina, que es bastante más lento.
- Los videos de más de 40 minutos se saltean (`youtube.max_duration_minutes`). Se puede
  subir, pero cada hora de video son varios minutos de procesamiento.
- Las playlists **privadas** no se pueden leer sin cookies de YouTube. Que la deje en
  *no listada*: nadie la encuentra, pero la herramienta la lee.
- Todo cae en el **mismo** catálogo e informes que Instagram. Una herramienta que aparece
  en un reel y en un video de YouTube se cuenta como una sola, con dos menciones.

## Cuando algo se rompe

| Síntoma | Qué es | Qué hacés |
|---|---|---|
| `sesion expirada` | La cookie dejó de valer | Repetí el *Paso 4* |
| `coleccion no encontrada` | El nombre no coincide | Pedile el nombre exacto; distingue acentos y espacios |
| `accion bloqueada` / `limite de peticiones` | Instagram frenó la cuenta | Pará 24 h. Después corré sin `--enable-comments` |
| `No encuentro el binario claude` | El agente no está en el PATH | Reinstalá Claude Code o usá `ai.provider: "openrouter"` con una key propia |
| `no encuentro ffmpeg` | Falta ffmpeg | Instalalo (*Paso 1*). Sin él solo se analiza la portada |
| `yt-dlp fallo ... 429` | YouTube limitó los pedidos | Es pasajero. Si era solo subtítulos, siguió con whisper |
| Un elemento con error | Caso suelto | No importa: la corrida sigue. `instapull status` los lista |

El README tiene la sección 12 con más casos. Antes de inventar una solución, mirá ahí.

## Qué NO hacer

- No subir los topes de comentarios, follows o pedidos por minuto.
- No commitear `.env`, `config.yaml`, `data/`, `output/` ni `logs/`.
- No cambiar el modelo de IA a uno pago sin preguntarle antes.
- No borrar `data/instapull.db`: es la memoria de todo lo ya analizado. Si se borra, la
  próxima corrida reprocesa todo desde cero.
- No procesar los guardados de una cuenta que no sea suya.
