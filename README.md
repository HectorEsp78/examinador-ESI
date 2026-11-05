# Examinador · Exámenes UCLM

Aplicación web estática para practicar los exámenes de **Redes I**, **Redes II** y
**Sistemas Distribuidos** de la Escuela Superior de Informática de la UCLM.

Muestra el PDF original y permite responder haciendo clic directamente sobre los
cuadros de las opciones. Al terminar, el botón **Corregir** indica qué respuestas
son correctas, cuáles fallaste y la puntuación obtenida.

> Herramienta de práctica no oficial. Los PDFs pertenecen a sus autores y a la
> UCLM; se incluyen únicamente con fines educativos.

## Características

- **180 exámenes** de las tres asignaturas, organizados en cursos desplegables y ordenados por prueba (P1, P2, recuperaciones y extraordinarias).
- **162 exámenes corregibles** con un total de **2.867 preguntas tipo test**.
- 18 exámenes en **modo lectura** (PDFs escaneados o sin solución reconocible).
- Respuesta haciendo clic en el propio PDF o desde la hoja de respuestas lateral.
- Zoom del PDF para leer mejor en pantallas pequeñas.
- Corrección con respuesta marcada, respuesta correcta y puntuación.
- Soporte de preguntas de **opción múltiple**.
- Penalizaciones leídas del enunciado: sin penalización, cada N fallos, por fallo
  o fracción de la nota de la pregunta.
- **Historial de intentos**: cada vez que corriges un examen se guarda un intento
  nuevo; al reiniciar el examen se borran las respuestas actuales, pero no el
  historial.
- **Progreso por asignatura** en la portada: porcentaje de exámenes aprobados
  (mejor intento ≥ 50 %) sobre exámenes resueltos, número de intentos y mejor
  resultado de cada examen.
- **Temario de Sistemas Distribuidos**: cada pregunta de SSDD puede abrir las
  diapositivas relacionadas del temario, con un visor PDF y un explorador por
  tema y página.
- Progreso guardado en `localStorage`: puedes cerrar y volver más tarde.
- No necesita backend: todo se sirve como archivos estáticos desde el mismo sitio.
- Preparada para publicarse gratis con **GitHub Pages**.

## Estructura

```
.
├── app/                      # Aplicación que se publica
│   ├── index.html
│   ├── styles.css
│   ├── js/app.js             # Catálogo, visor PDF.js, respuestas y corrección
│   ├── data/exams.json       # Catálogo, preguntas, opciones y soluciones
│   ├── data/ssdd_temario.json# Índice de diapositivas y sugerencias por pregunta
│   ├── pdfs/                 # Copias de los PDFs que muestra la app
│   ├── temario/ssdd/         # Copia de las diapositivas de SSDD
│   └── vendor/pdfjs/         # PDF.js, cmaps y fuentes estándar
├── temario/ssdd/             # PDFs originales del temario de SSDD
├── tools/build_exams.py      # Genera data/exams.json y copia los PDFs
├── tools/build_temario.py    # Genera ssdd_temario.json y copia las diapositivas
├── past-exams/               # Clon original de UCLM-ESI/past-exams (no se sube)
├── .github/workflows/pages.yml
├── LICENSE
└── README.md
```

`past-exams/` está en `.gitignore` porque es un repositorio anidado. La app es
autocontenida: los PDFs y las diapositivas que necesita ya están copiados dentro
de `app/`.

## Ver la app en local

No abras `app/index.html` con `file://`: el navegador bloqueará `fetch()` y el
worker de PDF.js. Sirve la carpeta con cualquier servidor estático:

```bash
python3 -m http.server 8000 --directory app
```

Abre <http://localhost:8000>.

También puedes usar:

```bash
npx serve app
# o
cd app && php -S localhost:8000
```

## Regenerar el catálogo y los datos

Solo es necesario si añades, quitas o cambias exámenes en `past-exams/`.

Requisitos:

- Python 3.9 o superior.
- `pdftohtml` y `pdftotext` de **poppler-utils**.
  - Debian/Ubuntu: `sudo apt install poppler-utils`
  - macOS: `brew install poppler`
  - Windows: instala Poppler y añade su carpeta `bin` al `PATH`.

```bash
python3 tools/build_exams.py
```

El script:

1. Empareja cada PDF sin corregir con su versión `.solved.pdf`.
2. Usa el PDF corregido como documento visible y oculta los cuadros marcados.
3. Extrae coordenadas de preguntas, opciones y marcas de solución.
4. Reparte los puntos de bloques y subapartados.
5. Detecta la penalización en el enunciado.
6. Copia los PDFs a `app/pdfs/` y escribe `app/data/exams.json`.

Los PDFs de `past-exams/` que no empiezan por `redes1_`, `redes2_` o `ssdd_` se
ignoran. Los duplicados exactos también se descartan.

## Publicar en GitHub Pages

Esta carpeta ya está inicializada como repositorio Git y tiene un commit inicial.
Solo falta asociarla a tu repositorio de GitHub:

1. Crea un repositorio vacío en GitHub (por ejemplo, `examinador`).
2. Desde la raíz de este proyecto:

   ```bash
   git remote add origin git@github.com:TU_USUARIO/examinador.git
   git push -u origin main
   ```

   Si prefieres empezar de cero:

   ```bash
   git init -b main
   git add .
   git commit -m "Examinador: app de práctica de exámenes"
   git remote add origin git@github.com:TU_USUARIO/examinador.git
   git push -u origin main
   ```

3. En GitHub, entra en **Settings → Pages**.
4. En **Build and deployment → Source**, elige **GitHub Actions**.
5. El workflow `.github/workflows/pages.yml` se ejecutará al hacer push a `main`.
6. Cuando termine, la app estará en:

   ```
   https://TU_USUARIO.github.io/examinador/
   ```

No hace falta configurar nada más: todas las rutas de la app son relativas, así
que funciona tanto en la raíz de un dominio como en un subdirectorio de proyecto.

### Tamaño del repositorio

La app ocupa unos **67 MB**, principalmente por los PDFs de examen (55 MB), las
diapositivas de SSDD (3,7 MB) y PDF.js (4,1 MB). Ningún archivo supera los
100 MB, el límite de GitHub. El repositorio queda muy por debajo del límite
blando de 1 GB.

## Cómo se calcula la nota

- Cada pregunta correcta suma sus puntos.
- Las preguntas en blanco no suman ni restan.
- Las incorrectas aplican la penalización indicada en el PDF:
  - `Cada 3 fallos restan 1 punto` (solo preguntas con 4 opciones o menos, si así
    lo indica el enunciado).
  - `Cada fallo resta X puntos`.
  - `Cada fallo resta 1/N de la nota de la pregunta`.
  - `Las respuestas incorrectas no restan`.
- La nota se muestra sobre los puntos de las preguntas tipo test corregibles.
  Si el examen completo incluye problemas o partes no tipo test, se indica el
  total oficial del examen en el resultado.
- Algunos PDFs antiguos tienen erratas en los puntos por pregunta (por ejemplo,
  marcan `(5p)` en un test de 8 puntos). En esos casos la puntuación se normaliza
  al total declarado en el enunciado.

## Historial, intentos y tasa de aprobados

Cada vez que pulsas **Corregir** se añade un intento al historial del examen.
El historial se guarda en la misma entrada de `localStorage` que las respuestas,
así que no se pierde al cerrar el navegador. **Reiniciar** borra las respuestas
actuales y el resultado en pantalla, pero conserva los intentos anteriores.

La portada muestra tres tarjetas, una por asignatura. El porcentaje se calcula
así:

- **Numerador:** exámenes corregibles distintos cuyo mejor intento alcanza el
  50 % o más.
- **Denominador:** exámenes corregibles distintos con al menos un intento
  guardado.
- Un examen con varios intentos cuenta una sola vez; para saber si está aprobado
  se usa su mejor intento.

El histórico de un examen concreto muestra la fecha, la puntuación, el porcentaje,
la etiqueta Aprobado/Suspenso y el desglose de aciertos, fallos y preguntas en
blanco. Las correcciones antiguas guardadas antes de existir el historial se
migran como primer intento al abrir el examen.

## Temario de Sistemas Distribuidos

La app incluye cuatro temas de SSDD en `app/temario/ssdd/`:

- Introducción y conceptos básicos.
- Comunicación indirecta.
- Diseño de protocolos.
- Invocación remota.

Cada pregunta de SSDD muestra un botón **Temario** en la hoja de respuestas. Al
pulsarlo se abre un visor con hasta tres diapositivas sugeridas y un explorador
para cambiar de tema o de página. Las sugerencias se generan con un mapeo
heurístico bilingüe (español/inglés) a partir del texto de la pregunta y de la
respuesta correcta. No es una correspondencia manual: puede haber preguntas sin
sugerencias claras (por ejemplo, temas que no están en estos cuatro temas) y
alguna sugerencia aproximada. En esos casos se puede explorar el temario completo
desde el selector.

Para regenerar el índice y copiar las diapositivas a la app:

```bash
python3 tools/build_temario.py
```

El script necesita los PDFs originales en `temario/ssdd/` y las herramientas
`pdfinfo` y `pdftotext` de poppler-utils. Escribe
`app/data/ssdd_temario.json` y copia los PDFs a `app/temario/ssdd/`. Si añades o
cambias diapositivas, actualiza la lista `DECKS` del script y vuelve a ejecutarlo.

## Añadir nuevos exámenes

1. Coloca el PDF en `past-exams/` con el nombre `asignatura_CURSO_CODIGO.pdf`
   (por ejemplo, `redes2_2627_P1.pdf`).
2. Si tienes la versión corregida, guárdala como
   `redes2_2627_P1.solved.pdf`. La app usará la versión corregida y ocultará las
   marcas.
3. Ejecuta `python3 tools/build_exams.py`.
4. Revisa el resultado en local.
5. Haz commit de `app/data/exams.json` y de los PDFs nuevos de `app/pdfs/`.

## Créditos y licencia

- Código de la aplicación: licencia MIT (ver `LICENSE`).
- PDFs: recopilación del repositorio
  [UCLM-ESI/past-exams](https://github.com/UCLM-ESI/past-exams). Los derechos
  pertenecen a sus autores y a la Universidad de Castilla-La Mancha.
- [PDF.js](https://mozilla.github.io/pdf.js/) (Mozilla, Apache 2.0) incluido en
  `app/vendor/pdfjs/`.

## Problemas frecuentes

**No carga el catálogo o el PDF.** Estás abriendo la app con `file://`. Usa un
servidor local o GitHub Pages.

**El PDF se ve pero las opciones no están alineadas.** El generador usa las
coordenadas del texto del PDF. Si el PDF es una imagen escaneada sin capa de
texto, aparecerá en modo lectura. Para PDFs nuevos, comprueba que `pdftotext`
extrae texto.

**Una pregunta no se corrige.** El generador solo incluye preguntas con al menos
dos opciones y una marca de solución reconocible. Las preguntas sin marca se
omiten de la corrección, aunque siguen visibles en el PDF.

**La puntuación no coincide con el examen.** Revisa la nota que aparece en el
resultado: puede que el examen tenga partes no tipo test o una errata en los
puntos por pregunta. El detalle pregunta a pregunta está siempre disponible.
