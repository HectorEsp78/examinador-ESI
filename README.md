# Examinador · Exámenes UCLM

Aplicación web estática para practicar los exámenes de **Redes I**, **Redes II** y
**Sistemas Distribuidos** de la Escuela Superior de Informática de la UCLM.

Muestra el PDF original y permite responder haciendo clic directamente sobre los
cuadros de las opciones. Al terminar, el botón **Corregir** indica qué respuestas
son correctas, cuáles fallaste y la puntuación obtenida.

> Herramienta de práctica no oficial. Los PDFs pertenecen a sus autores y a la
> UCLM; se incluyen únicamente con fines educativos.

## Características

- **180 exámenes** de las tres asignaturas, ordenados por curso y prueba.
- **162 exámenes corregibles** con un total de **2.867 preguntas tipo test**.
- 18 exámenes en **modo lectura** (PDFs escaneados o sin solución reconocible).
- Respuesta haciendo clic en el propio PDF o desde la hoja de respuestas lateral.
- Zoom del PDF para leer mejor en pantallas pequeñas.
- Corrección con respuesta marcada, respuesta correcta y puntuación.
- Soporte de preguntas de **opción múltiple**.
- Penalizaciones leídas del enunciado: sin penalización, cada N fallos, por fallo
  o fracción de la nota de la pregunta.
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
│   ├── pdfs/                 # Copias de los PDFs que muestra la app
│   └── vendor/pdfjs/         # PDF.js, cmaps y fuentes estándar
├── tools/build_exams.py      # Genera data/exams.json y copia los PDFs
├── past-exams/               # Clon original de UCLM-ESI/past-exams (no se sube)
├── .github/workflows/pages.yml
├── LICENSE
└── README.md
```

`past-exams/` está en `.gitignore` porque es un repositorio anidado. La app es
autocontenida: los PDFs que necesita ya están copiados en `app/pdfs/`.

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

La app ocupa unos **63 MB**, principalmente por los PDFs (55 MB). Ningún archivo
supera los 100 MB, el límite de GitHub. El repositorio queda muy por debajo del
límite blando de 1 GB.

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
