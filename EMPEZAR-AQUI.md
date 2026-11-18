# Empezá acá

InstaPull lee los posts que **guardás** en Instagram (y los videos de una playlist de
YouTube), los mira con inteligencia artificial y te arma una lista ordenada de las
herramientas de IA que aparecen: qué hace cada una, el link para probarla y qué tan
interesante es. Si el post dice "comentá X y te mando el link", también puede comentar y
quedarse con el link que llega por mensaje.

Al final te queda un catálogo que abrís en el navegador, y una planilla.

## No tenés que instalar nada vos

Abrí **Claude Code** en la carpeta de este proyecto y mandale este mensaje:

> Leé el archivo CLAUDE.md de este repo y dejá InstaPull funcionando. Yo no soy
> programador: encargate vos de todo e indicame paso a paso lo que tengo que hacer con el
> navegador.

Él se encarga del resto: instala lo que falte, configura todo y te va pidiendo de a una
cosa. Vas a tener que hacer tres cosas con tus manos, y te va a explicar cada una:

1. **Copiar una cookie de Instagram.** Es un código largo que le dice a la herramienta
   "entrá con mi cuenta". Se copia del navegador donde ya estás logueado. Claude te dice
   dónde tocar, paso por paso. No hay que poner la contraseña en ninguna parte.
2. **Crear una colección de guardados llamada `AI`.** De ahí en adelante, cada post de
   inteligencia artificial lo guardás en esa colección. Es la forma recomendada: cada
   corrida procesa solo lo nuevo y tarda unos minutos.
   *Alternativa:* también puede leer **todo** lo que ya tenés guardado desde siempre, sin
   crear nada. Funciona igual, pero son cientos de posts, hay que hacerlo de a tandas en
   varios días, y entra bastante ruido de cosas que no son de IA. Lo ideal es hacer las
   dos: la colección `AI` para el día a día, y el archivo viejo de a poco.
3. **(Opcional) Crear una playlist de YouTube.** Si querés que analice videos largos de
   YouTube, hacé una playlist *no listada* y guardá ahí los videos. Le pasás el link a
   Claude y listo.

## Lo que tenés que saber antes de arrancar

- **No cuesta plata.** El análisis usa tu propia suscripción de Claude. No hay que sacar
  ninguna tarjeta ni ninguna clave de API.
- **Usá una cuenta de Instagram secundaria si podés.** La herramienta comenta y sigue
  cuentas en tu nombre cuando el post lo pide para dar el link. Son acciones públicas, y si
  Instagram las ve demasiado seguido puede limitar la cuenta un rato. Los topes están
  puestos bajos a propósito. Si no querés que comente nada, decile a Claude que lo apague:
  el análisis funciona igual.
- **Tarda.** Cada post lleva entre medio minuto y dos minutos, porque baja el video, lo
  transcribe y lo mira entero. Diez posts son unos quince minutos. No es un bug.
- **No repite trabajo.** Lo ya analizado se saltea solo, así que podés correrlo todos los
  días sin problema.

## Lo que te queda

- `output/catalogo.html` — el catálogo de herramientas, se abre en el navegador. Es lo que
  vas a mirar casi siempre.
- `output/informe.md` — el detalle post por post.
- `output/items.csv` — para abrir en Excel.

Si algo se rompe o no entendés un mensaje, copiáselo a Claude y pedile que lo arregle: en
`CLAUDE.md` tiene la tabla de qué hacer en cada caso. El manual técnico completo, por si
alguna vez hace falta, está en [README.md](README.md).
