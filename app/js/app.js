import * as pdfjsLib from "../vendor/pdfjs/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "../vendor/pdfjs/pdf.worker.min.mjs",
  import.meta.url
).href;

const CMAP_URL = new URL("../vendor/pdfjs/cmaps/", import.meta.url).href;
const STANDARD_FONTS_URL = new URL(
  "../vendor/pdfjs/standard_fonts/",
  import.meta.url
).href;

const SUBJECT_META = {
  redes1: { name: "Redes I", color: "#0e7490" },
  redes2: { name: "Redes II", color: "#7c3aed" },
  ssdd: { name: "Sistemas Distribuidos", color: "#b45309" },
};

const SUBJECT_ORDER = { redes1: 0, redes2: 1, ssdd: 2 };

const STORAGE_PREFIX = "examinador:v1:";
const PASS_PERCENTAGE = 50;

const state = {
  data: null,
  exam: null,
  answers: {},
  corrected: false,
  result: null,
  attempts: [],
  attemptsByExam: new Map(),
  panelOpen: false,
  filter: { subject: "all", query: "" },
  renderToken: 0,
  pdfDoc: null,
  zoom: 1,
  toastTimer: null,
  temario: null,
  temarioDocs: new Map(),
  temarioToken: 0,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

/* --------------------------------------------------------------------------
   Utilidades
   -------------------------------------------------------------------------- */

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fold(value) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function formatPoints(value) {
  const number = Number(value) || 0;
  if (Number.isInteger(number)) return String(number);
  return number
    .toFixed(2)
    .replace(/0+$/, "")
    .replace(/\.$/, "");
}

function percent(value, total) {
  if (!total) return "0%";
  return `${Math.max(0, Math.min(100, (value / total) * 100))}%`;
}

function plural(value, singular, pluralWord) {
  return `${value} ${value === 1 ? singular : pluralWord}`;
}

function showToast(message) {
  const toast = $("#toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => toast.classList.remove("show"), 3200);
}

function normaliseAnswers(exam, raw) {
  const valid = new Set(exam.questions.map((q) => q.id));
  const letters = new Map(exam.questions.map((q) => [q.id, new Set(q.options.map((o) => o.letter))]));
  const answers = {};
  if (!raw || typeof raw !== "object") return answers;
  for (const [qid, selected] of Object.entries(raw)) {
    if (!valid.has(qid) || !Array.isArray(selected)) continue;
    const allowed = letters.get(qid);
    const clean = [...new Set(selected.filter((letter) => allowed.has(letter)))];
    if (clean.length) answers[qid] = clean.sort();
  }
  return answers;
}

function normaliseAttempt(exam, raw) {
  if (!raw || typeof raw !== "object") return null;
  const percentage = Number(raw.percentage);
  if (!Number.isFinite(percentage)) return null;
  const score = Number(raw.score);
  const maxScore = Number(raw.maxScore);
  return {
    at: typeof raw.at === "string" ? raw.at : "",
    score: Number.isFinite(score) ? score : 0,
    maxScore: Number.isFinite(maxScore) ? maxScore : exam.maxScore || 0,
    percentage: Math.max(0, Math.min(100, percentage)),
    correct: Number(raw.correct) || 0,
    wrong: Number(raw.wrong) || 0,
    blank: Number(raw.blank) || 0,
    penaltyPoints: Number(raw.penaltyPoints) || 0,
    passed: Boolean(raw.passed ?? percentage >= PASS_PERCENTAGE),
    answers: normaliseAnswers(exam, raw.answers),
  };
}

function loadProgress(exam) {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + exam.id);
    if (!raw) return { answers: {}, corrected: false, attempts: [] };
    const parsed = JSON.parse(raw);
    const attempts = Array.isArray(parsed.attempts)
      ? parsed.attempts
          .map((attempt) => normaliseAttempt(exam, attempt))
          .filter(Boolean)
      : [];
    return {
      answers: normaliseAnswers(exam, parsed.answers),
      corrected: Boolean(parsed.corrected),
      attempts,
    };
  } catch {
    return { answers: {}, corrected: false, attempts: [] };
  }
}

function saveProgress() {
  if (!state.exam) return;
  try {
    localStorage.setItem(
      STORAGE_PREFIX + state.exam.id,
      JSON.stringify({
        answers: state.answers,
        corrected: state.corrected,
        attempts: state.attempts,
        updatedAt: new Date().toISOString(),
      })
    );
  } catch {
    /* almacenamiento lleno o bloqueado: la app sigue funcionando */
  }
}

function makeAttempt(result) {
  if (!result) return null;
  return {
    at: new Date().toISOString(),
    score: result.score,
    maxScore: result.maxScore,
    percentage: result.percentage,
    correct: result.correct,
    wrong: result.wrong,
    blank: result.blank,
    penaltyPoints: result.penaltyPoints,
    passed: result.percentage >= PASS_PERCENTAGE,
    answers: Object.fromEntries(
      Object.entries(state.answers).map(([qid, letters]) => [qid, [...letters]])
    ),
  };
}

function recordAttempt(result) {
  const attempt = makeAttempt(result);
  if (!attempt) return null;
  state.attempts.push(attempt);
  return attempt;
}

function loadAllProgress() {
  const cache = new Map();
  if (!state.data) return cache;
  for (const exam of state.data.exams) {
    cache.set(exam.id, loadProgress(exam).attempts);
  }
  state.attemptsByExam = cache;
  return cache;
}

function subjectProgress() {
  const stats = Object.fromEntries(
    state.data.subjects.map((subject) => [
      subject.id,
      { solved: 0, passed: 0, attempts: 0, best: 0 },
    ])
  );
  for (const exam of state.data.exams) {
    if (!exam.interactive) continue;
    const attempts = state.attemptsByExam.get(exam.id) || [];
    const stat = stats[exam.subject];
    if (!stat || !attempts.length) continue;
    stat.solved += 1;
    stat.attempts += attempts.length;
    const best = Math.max(...attempts.map((attempt) => attempt.percentage));
    stat.best = Math.max(stat.best, best);
    if (best >= PASS_PERCENTAGE) stat.passed += 1;
  }
  return stats;
}

function formatAttemptDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Sin fecha";
  return date.toLocaleString("es-ES", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

function getExam(id) {
  return state.data?.exams.find((exam) => exam.id === id) || null;
}

function pdfUrl(exam) {
  return new URL(exam.pdf, document.baseURI).href;
}

/* --------------------------------------------------------------------------
   Arranque y rutas
   -------------------------------------------------------------------------- */

async function init() {
  try {
    const [response, temarioResponse] = await Promise.all([
      fetch("data/exams.json", { cache: "no-cache" }),
      fetch("data/ssdd_temario.json", { cache: "no-cache" }).catch(() => null),
    ]);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();
    if (temarioResponse?.ok) {
      try {
        state.temario = await temarioResponse.json();
      } catch {
        state.temario = null;
      }
    }
  } catch (error) {
    $("#view").innerHTML = `
      <div class="empty-state" style="margin-top:2rem">
        <strong>No se pudo cargar el catálogo de exámenes.</strong><br />
        Comprueba que <code>data/exams.json</code> existe y que estás sirviendo la app
        desde un servidor (no con <code>file://</code>).
      </div>`;
    console.error(error);
    return;
  }

  window.addEventListener("hashchange", route);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeModal();
      closePanel();
    }
  });
  $("#panel-backdrop")?.addEventListener("click", closePanel);
  route();
}

async function route() {
  const match = location.hash.match(/^#\/exam\/([^/?#]+)/);
  if (match) {
    await openExam(decodeURIComponent(match[1]));
  } else {
    renderCatalog();
  }
}

/* --------------------------------------------------------------------------
   Catálogo
   -------------------------------------------------------------------------- */

function renderProgressSummary(progress) {
  return `
    <section class="progress-summary" aria-labelledby="progress-summary-title">
      <div class="progress-summary-head">
        <h2 id="progress-summary-title">Tu progreso</h2>
        <span>Aprobado ≥ ${PASS_PERCENTAGE}% · sobre exámenes resueltos</span>
      </div>
      <div class="progress-summary-grid">
        ${state.data.subjects
          .map((subject) => {
            const meta = SUBJECT_META[subject.id] || {
              name: subject.name,
              color: "#8b1e3f",
            };
            const stat = progress[subject.id] || {
              solved: 0,
              passed: 0,
              attempts: 0,
              best: 0,
            };
            const value = stat.solved
              ? Math.round((stat.passed / stat.solved) * 100)
              : null;
            const detail = stat.solved
              ? `${stat.passed} de ${stat.solved} aprobados · ${plural(
                  stat.attempts,
                  "intento",
                  "intentos"
                )}`
              : "Sin exámenes resueltos";
            return `
              <article class="progress-card" style="--accent:${meta.color}">
                <div class="progress-card-head">
                  <span class="subject-dot" aria-hidden="true"></span>
                  <h3>${escapeHtml(subject.name)}</h3>
                </div>
                <div class="progress-card-value">
                  <strong>${value === null ? "—" : `${value}%`}</strong>
                  <span>aprobados</span>
                </div>
                <div class="progress-track progress-card-track" aria-hidden="true">
                  <span style="width:${value === null ? 0 : value}%"></span>
                </div>
                <p>${escapeHtml(detail)}</p>
              </article>`;
          })
          .join("")}
      </div>
    </section>`;
}

function renderCatalog() {
  state.renderToken += 1;
  state.exam = null;
  state.panelOpen = false;
  if (state.pdfDoc) {
    state.pdfDoc.destroy().catch(() => {});
    state.pdfDoc = null;
  }
  closePanel();
  $("#topbar-right").innerHTML = "";

  loadAllProgress();
  const progressStats = subjectProgress();
  const exams = state.data.exams;
  const interactive = exams.filter((exam) => exam.interactive);
  const totalQuestions = interactive.reduce((sum, exam) => sum + exam.questionCount, 0);
  const totalPdfs = exams.length;

  const subjectCounts = Object.fromEntries(
    state.data.subjects.map((subject) => [
      subject.id,
      exams.filter((exam) => exam.subject === subject.id).length,
    ])
  );

  $("#view").innerHTML = `
    <section class="hero">
      <div class="hero-copy">
        <span class="eyebrow">Práctica de exámenes</span>
        <h1>Examinador</h1>
        <p>
          Elige un curso, abre una prueba y responde directamente sobre el PDF.
          Al terminar, corrige para ver aciertos, fallos y puntuación.
        </p>
        <div class="hero-stats">
          <div class="hero-stat">
            <strong>${totalPdfs}</strong>
            <span>exámenes</span>
          </div>
          <div class="hero-stat">
            <strong>${interactive.length}</strong>
            <span>corregibles</span>
          </div>
          <div class="hero-stat">
            <strong>${totalQuestions.toLocaleString("es-ES")}</strong>
            <span>preguntas</span>
          </div>
        </div>
      </div>
      <div class="hero-art" aria-hidden="true">
        <div class="paper-stack">
          <div class="paper-sheet">
            <h3>Redes de Computadores II</h3>
            <div class="paper-line short"></div>
            <div class="paper-question">1. ¿Cuál es la limitación principal de un servidor TCP iterativo?</div>
            <div class="paper-option"><i></i> a) No puede aceptar conexiones TCP y UDP a la vez.</div>
            <div class="paper-option"><i></i> b) Necesita un puerto distinto por cada cliente.</div>
            <div class="paper-option active"><i></i> c) No puede atender a otro cliente mientras sirve al actual.</div>
            <div class="paper-option"><i></i> d) Solo funciona en la misma red local.</div>
            <div class="paper-question" style="margin-top:1.1rem">2. ¿Qué hace select() en un servidor?</div>
            <div class="paper-option"><i></i> a) Crea un hilo por cliente.</div>
            <div class="paper-option active"><i></i> b) Vigila varios descriptores y atiende los activos.</div>
          </div>
        </div>
      </div>
    </section>

    ${renderProgressSummary(progressStats)}

    <div class="catalog-toolbar">
      <div class="tabs" role="tablist" aria-label="Asignaturas">
        <button class="tab active" data-subject="all" role="tab">
          Todos <span class="tab-count">${exams.length}</span>
        </button>
        ${state.data.subjects
          .map(
            (subject) => `
          <button class="tab" data-subject="${subject.id}" role="tab">
            ${escapeHtml(subject.name)}
            <span class="tab-count">${subjectCounts[subject.id] || 0}</span>
          </button>`
          )
          .join("")}
      </div>
      <div class="search-wrap">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="11" cy="11" r="7"></circle>
          <path d="m20 20-3.5-3.5"></path>
        </svg>
        <input
          id="search"
          class="search-input"
          type="search"
          placeholder="Buscar por año, prueba, asignatura…"
          autocomplete="off"
          value="${escapeHtml(state.filter.query)}"
        />
      </div>
    </div>

    <p class="results-count" id="results-count"></p>
    <div class="year-list" id="exam-grid"></div>

    <footer class="site-footer">
      <p>
        <strong>Examinador</strong> es una herramienta de práctica no oficial.
        Los PDFs son exámenes de la Escuela Superior de Informática de la UCLM y
        pertenecen a sus autores.
      </p>
      <p>
        Basado en el repositorio
        <a href="https://github.com/UCLM-ESI/past-exams" target="_blank" rel="noopener">
          UCLM-ESI/past-exams
        </a>.
        Las soluciones se leen de los cuadros marcados en los PDFs corregidos.
      </p>
    </footer>
  `;

  $$(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.subject === state.filter.subject);
    tab.addEventListener("click", () => {
      state.filter.subject = tab.dataset.subject;
      $$(".tab").forEach((other) =>
        other.classList.toggle("active", other === tab)
      );
      renderGrid();
    });
  });

  $("#search").addEventListener("input", (event) => {
    state.filter.query = event.target.value;
    renderGrid();
  });

  renderGrid();
}

function examTypeRank(exam) {
  const code = String(exam.code || "").toUpperCase();
  if (/^(EXTRA-)?P1X/.test(code)) return 50;
  if (/^(EXTRA-)?P2X/.test(code)) return 60;
  if (/^P1R/.test(code)) return 30;
  if (/^P2R/.test(code)) return 40;
  if (/^P1/.test(code)) return 10;
  if (/^P2/.test(code)) return 20;
  if (/^P3/.test(code)) return 70;
  if (/^C[123]/.test(code)) return 80;
  if (/^(FINAL|ORDINARIO)/.test(code)) return 90;
  return 100;
}

function renderExamCard(exam) {
  const meta = SUBJECT_META[exam.subject] || {
    name: exam.subjectName,
    color: "#8b1e3f",
  };
  const details = exam.interactive
    ? `${plural(exam.questionCount, "pregunta", "preguntas")} · ${formatPoints(exam.maxScore)} pts`
    : plural(exam.pageCount, "página", "páginas");
  const hasNonTest =
    exam.interactive &&
    exam.declaredTotal &&
    Math.abs(exam.declaredTotal - exam.maxScore) > 0.01;
  const language = exam.language === "en" ? '<span class="lang-pill">EN</span>' : "";
  const attempts = state.attemptsByExam.get(exam.id) || [];
  const best = attempts.length
    ? Math.max(...attempts.map((attempt) => attempt.percentage))
    : null;
  const history =
    best === null
      ? ""
      : `<span class="card-history ${best >= PASS_PERCENTAGE ? "passed" : ""}">
          ${plural(attempts.length, "intento", "intentos")} · mejor ${Math.round(best)}%
        </span>`;

  return `
    <a
      class="exam-card"
      href="#/exam/${encodeURIComponent(exam.id)}"
      style="--accent:${meta.color}"
    >
      <div class="card-top">
        <span class="subject-pill">${escapeHtml(meta.name)}</span>
        ${language}
      </div>
      <h3>${escapeHtml(exam.codeLabel)}</h3>
      <div class="card-meta">
        <span>${details}</span>
        ${hasNonTest ? '<span class="card-note">incluye parte no tipo test</span>' : ""}
        ${history}
      </div>
      <div class="card-footer">
        <span class="badge ${exam.interactive ? "ok" : "readonly"}">
          ${exam.interactive ? "Corregible" : "Solo lectura"}
        </span>
        <span class="card-cta">Abrir →</span>
      </div>
    </a>`;
}

function renderGrid() {
  const grid = $("#exam-grid");
  const count = $("#results-count");
  if (!grid || !state.data) return;

  const query = fold(state.filter.query.trim());
  const searching = Boolean(query);
  const list = state.data.exams.filter((exam) => {
    if (state.filter.subject !== "all" && exam.subject !== state.filter.subject) {
      return false;
    }
    if (!query) return true;
    const haystack = fold(
      [
        exam.title,
        exam.subjectName,
        exam.year,
        exam.code,
        exam.codeLabel,
        exam.language === "en" ? "english inglés" : "español spanish",
        exam.original,
      ].join(" ")
    );
    return haystack.includes(query);
  });

  list.sort(
    (a, b) =>
      b.yearSort - a.yearSort ||
      (SUBJECT_ORDER[a.subject] ?? 9) - (SUBJECT_ORDER[b.subject] ?? 9) ||
      examTypeRank(a) - examTypeRank(b) ||
      a.codeLabel.localeCompare(b.codeLabel, "es") ||
      a.language.localeCompare(b.language) ||
      a.id.localeCompare(b.id)
  );

  const byYear = new Map();
  for (const exam of list) {
    const year = exam.year || "Sin curso";
    if (!byYear.has(year)) byYear.set(year, []);
    byYear.get(year).push(exam);
  }

  const examWord = list.length === 1 ? "examen" : "exámenes";
  const yearWord = byYear.size === 1 ? "año" : "años";
  count.innerHTML = `<strong>${list.length}</strong> ${examWord} en <strong>${byYear.size}</strong> ${yearWord}`;

  if (!list.length) {
    grid.innerHTML = `
      <div class="empty-state">
        No hay exámenes que coincidan con el filtro.
      </div>`;
    grid.dataset.rendered = "true";
    grid.dataset.searching = String(searching);
    return;
  }

  const openYears = new Set(
    $$(".year-group[open]", grid).map((group) => group.dataset.year)
  );
  const firstYear = byYear.keys().next().value;
  const noOpenYear = ![...openYears].some((year) => byYear.has(year));
  if (
    !grid.dataset.rendered ||
    (grid.dataset.searching === "true" && !searching) ||
    noOpenYear
  ) {
    openYears.clear();
    if (firstYear) openYears.add(firstYear);
  }
  if (searching) {
    for (const year of byYear.keys()) openYears.add(year);
  }

  grid.innerHTML = [...byYear.entries()]
    .map(([year, yearExams]) => {
      const interactiveCount = yearExams.filter((exam) => exam.interactive).length;
      const bySubject = new Map();
      for (const exam of yearExams) {
        if (!bySubject.has(exam.subject)) bySubject.set(exam.subject, []);
        bySubject.get(exam.subject).push(exam);
      }

      const showSubjectHeadings = state.filter.subject === "all";
      const subjectBlocks = state.data.subjects
        .map((subject) => {
          const subjectExams = bySubject.get(subject.id);
          if (!subjectExams?.length) return "";
          const meta = SUBJECT_META[subject.id] || {
            name: subject.name,
            color: "#8b1e3f",
          };
          const cards = subjectExams.map(renderExamCard).join("");
          if (!showSubjectHeadings) {
            return `<div class="exam-grid">${cards}</div>`;
          }
          return `
            <section class="subject-block" style="--accent:${meta.color}">
              <div class="subject-head">
                <span class="subject-dot" aria-hidden="true"></span>
                <h3>${escapeHtml(subject.name)}</h3>
                <span class="subject-count">${subjectExams.length}</span>
              </div>
              <div class="exam-grid">${cards}</div>
            </section>`;
        })
        .join("");

      return `
        <details class="year-group" data-year="${escapeHtml(year)}"${
          openYears.has(year) ? " open" : ""
        }>
          <summary class="year-summary">
            <span class="year-title">
              <span class="year-name">${escapeHtml(year)}</span>
              <span class="year-meta">${plural(
                yearExams.length,
                "examen",
                "exámenes"
              )} · ${interactiveCount} ${
                interactiveCount === 1 ? "corregible" : "corregibles"
              }</span>
            </span>
            <span class="year-chevron" aria-hidden="true"></span>
          </summary>
          <div class="year-body">${subjectBlocks}</div>
        </details>`;
    })
    .join("");

  grid.dataset.rendered = "true";
  grid.dataset.searching = String(searching);
}

/* --------------------------------------------------------------------------
   Vista de examen
   -------------------------------------------------------------------------- */

async function openExam(id) {
  const exam = getExam(id);
  if (!exam) {
    location.hash = "#/";
    return;
  }

  const saved = loadProgress(exam);
  state.exam = exam;
  state.answers = saved.answers;
  state.attempts = saved.attempts;
  state.corrected = Boolean(saved.corrected && exam.interactive);
  state.result = state.corrected ? gradeExam() : null;
  if (
    state.corrected &&
    state.result?.answered > 0 &&
    state.attempts.length === 0
  ) {
    // Migración de datos antiguos: conserva como primer intento la corrección ya guardada.
    recordAttempt(state.result);
    saveProgress();
  }
  state.panelOpen = false;
  state.zoom = 1;
  state.renderToken += 1;
  const token = state.renderToken;

  if (state.pdfDoc) {
    state.pdfDoc.destroy().catch(() => {});
    state.pdfDoc = null;
  }
  closePanel();
  renderExamShell(exam);
  updateAll();

  await renderPdf(exam, token);
}

function renderExamShell(exam) {
  const interactive = exam.interactive;
  const meta = SUBJECT_META[exam.subject] || {
    name: exam.subjectName,
    color: "#8b1e3f",
  };
  const originalUrl = pdfUrl(exam);

  $("#topbar-right").innerHTML = `
    <a class="btn ghost small" href="${escapeHtml(originalUrl)}" target="_blank" rel="noopener">
      PDF original
    </a>`;

  $("#view").innerHTML = `
    <div class="exam-toolbar">
      <a class="back-link" href="#/">← <span class="long">Exámenes</span></a>
      <div class="exam-heading">
        <h1>${escapeHtml(exam.codeLabel)} · ${escapeHtml(exam.subjectName)}</h1>
        <p>
          ${escapeHtml(exam.year || "")}
          · ${exam.language === "en" ? "Inglés" : "Español"}
          · ${plural(exam.pageCount, "página", "páginas")}
        </p>
      </div>
      <div class="toolbar-actions">
        <div class="zoom-control" aria-label="Zoom del documento">
          <button type="button" id="zoom-out" title="Alejar" aria-label="Alejar">−</button>
          <button type="button" id="zoom-fit" title="Ajustar al ancho">
            <span id="zoom-label">100%</span>
          </button>
          <button type="button" id="zoom-in" title="Acercar" aria-label="Acercar">+</button>
        </div>
        ${
          interactive
            ? `<button class="btn ghost" id="btn-sheet" type="button">
                Hoja <span class="long">de respuestas</span>
              </button>
              <button class="btn ghost" id="btn-history" type="button" ${
                state.attempts.length ? "" : "hidden"
              }>Historial</button>
              <button class="btn ghost" id="btn-reset" type="button">Reiniciar</button>
              <button class="btn primary" id="btn-correct" type="button">Corregir</button>`
            : ""
        }
      </div>
    </div>

    ${
      interactive
        ? `<div class="exam-progress-wrap">
            <div class="exam-progress-label">
              <span id="progress-text">0 respondidas</span>
              <strong id="progress-pct">0%</strong>
            </div>
            <div class="progress-track"><span id="progress-bar"></span></div>
          </div>`
        : ""
    }

    ${
      !interactive
        ? `<div class="readonly-banner">
            Este PDF no contiene preguntas tipo test con solución reconocible.
            Puedes consultarlo en modo lectura. Si crees que debería ser corregible,
            revisa que el PDF tenga los cuadros de respuesta marcados.
          </div>`
        : ""
    }

    <div class="exam-layout ${interactive ? "" : "single"}">
      <div class="document" id="document">
        <div class="pdf-loading">
          <span class="spinner"></span> Cargando documento…
        </div>
      </div>
      ${
        interactive
          ? `<aside class="answers-panel" id="answers-panel" aria-label="Hoja de respuestas">
              <div class="panel-head">
                <h2>Hoja de respuestas</h2>
                <span id="panel-count">0 / ${exam.questionCount}</span>
                <button class="panel-close" id="panel-close" type="button" aria-label="Cerrar hoja de respuestas">×</button>
              </div>
              <div class="panel-scroll" id="panel-scroll"></div>
            </aside>`
          : ""
      }
    </div>
  `;

  if (interactive) {
    $("#btn-correct")?.addEventListener("click", () => {
      if (state.corrected) showResultModal();
      else correctNow();
    });
    $("#btn-reset")?.addEventListener("click", resetAnswers);
    $("#btn-sheet")?.addEventListener("click", togglePanel);
    $("#btn-history")?.addEventListener("click", showHistoryModal);
    $("#panel-close")?.addEventListener("click", closePanel);
    $("#document")?.addEventListener("click", (event) => {
      const zone = event.target.closest(".option-zone");
      if (zone) selectOption(zone.dataset.q, zone.dataset.letter);
    });
    $("#answers-panel")?.addEventListener("click", (event) => {
      const temario = event.target.closest("[data-temario]");
      if (temario) {
        openTemario(temario.dataset.temario);
        return;
      }
      const option = event.target.closest(".q-opt");
      if (option) {
        selectOption(option.dataset.q, option.dataset.letter);
        return;
      }
      const head = event.target.closest("[data-scroll]");
      if (head) {
        scrollToQuestion(head.dataset.scroll);
        closePanel();
      }
    });
  }

  $("#zoom-out")?.addEventListener("click", () => setZoom(state.zoom - 0.25));
  $("#zoom-in")?.addEventListener("click", () => setZoom(state.zoom + 0.25));
  $("#zoom-fit")?.addEventListener("click", () => setZoom(1));
  applyZoom();
}

/* --------------------------------------------------------------------------
   Render del PDF y capas interactivas
   -------------------------------------------------------------------------- */

async function renderPdf(exam, token) {
  const container = $("#document");
  if (!container) return;

  try {
    const loadingTask = pdfjsLib.getDocument({
      url: pdfUrl(exam),
      cMapUrl: CMAP_URL,
      cMapPacked: true,
      standardFontDataUrl: STANDARD_FONTS_URL,
    });
    const pdf = await loadingTask.promise;
    if (token !== state.renderToken) {
      pdf.destroy().catch(() => {});
      return;
    }
    state.pdfDoc = pdf;
    container.innerHTML = "";

    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      if (token !== state.renderToken) return;
      await renderPdfPage(pdf, pageNumber, exam, token, container);
    }
    updateOptionClasses();
  } catch (error) {
    if (token !== state.renderToken || isRenderCancellation(error)) return;
    console.error(error);
    container.innerHTML = `
      <div class="empty-state">
        <strong>No se pudo mostrar el PDF.</strong><br />
        <a href="${escapeHtml(pdfUrl(exam))}" target="_blank" rel="noopener">Abrir el PDF original</a>
      </div>`;
  }
}

function isRenderCancellation(error) {
  return (
    error?.name === "RenderingCancelledException" ||
    /RenderingCancelledException/.test(String(error?.message || ""))
  );
}

async function renderPdfPage(pdf, pageNumber, exam, token, container) {
  const page = await pdf.getPage(pageNumber);
  if (token !== state.renderToken) return;

  const baseViewport = page.getViewport({ scale: 1 });
  const pageEl = document.createElement("div");
  pageEl.className = "pdf-page";
  pageEl.dataset.page = String(pageNumber - 1);
  pageEl.style.aspectRatio = `${baseViewport.width} / ${baseViewport.height}`;

  const canvas = document.createElement("canvas");
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const renderWidth = 1000;
  const scale = renderWidth / baseViewport.width;
  const viewport = page.getViewport({ scale });

  canvas.width = Math.max(1, Math.floor(viewport.width * dpr));
  canvas.height = Math.max(1, Math.floor(viewport.height * dpr));
  canvas.style.width = "100%";
  canvas.style.height = "auto";
  pageEl.appendChild(canvas);

  const overlay = document.createElement("div");
  overlay.className = "page-overlay";
  pageEl.appendChild(overlay);
  container.appendChild(pageEl);

  const context = canvas.getContext("2d", { alpha: false });
  try {
    await page.render({
      canvasContext: context,
      viewport,
      transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null,
    }).promise;
  } catch (error) {
    if (token !== state.renderToken || isRenderCancellation(error)) return;
    throw error;
  }

  if (token !== state.renderToken) return;
  addPageOverlays(overlay, exam, pageNumber - 1);
  updateOptionClasses();
}

function addPageOverlays(overlay, exam, pageIndex) {
  const pageSize =
    exam.pageSizes?.[pageIndex] || [exam.pageWidth || 595, exam.pageHeight || 842];
  const [pageW, pageH] = pageSize;
  if (!pageW || !pageH) return;

  const options = [];
  for (const question of exam.questions) {
    for (const option of question.options) {
      if (option.page === pageIndex) options.push({ question, option });
    }
  }

  // Primero las tapas blancas que ocultan los cuadros originales del PDF.
  for (const { option } of options) {
    const [x, y, w, h] = option.rect;
    const cover = document.createElement("span");
    cover.className = "marker-cover";
    cover.style.left = percent(x, pageW);
    cover.style.top = percent(y, pageH);
    cover.style.width = percent(w, pageW);
    cover.style.height = percent(h, pageH);
    overlay.appendChild(cover);
  }

  // Calcula zonas clicables que cubren también las respuestas partidas en dos
  // líneas. La zona llega hasta la siguiente opción de la misma columna, sin
  // invadir opciones de otras preguntas.
  const zoneRects = new Map();
  for (const { question, option } of options) {
    const [zx, zy, zw, zh] = option.zone;
    let nextTop = Infinity;
    for (const other of options) {
      if (other.question !== question) continue;
      const [ox, oy, ow] = other.option.zone;
      if (oy <= zy + 1) continue;
      if (ox + ow <= zx || ox >= zx + zw) continue;
      nextTop = Math.min(nextTop, oy);
    }
    const height =
      Number.isFinite(nextTop) && nextTop > zy
        ? Math.max(zh, Math.min(nextTop - zy, 90))
        : zh;
    zoneRects.set(option, [zx, zy, zw, height]);
  }

  // Después las zonas clicables, por encima de las tapas.
  for (const { question, option } of options) {
    const [x, y, w, h] = option.rect;
    const [zx, zy, zw, zh] = zoneRects.get(option) || option.zone;
    const zone = document.createElement("button");
    zone.type = "button";
    zone.className = "option-zone";
    zone.dataset.q = question.id;
    zone.dataset.letter = option.letter;
    zone.style.left = percent(zx, pageW);
    zone.style.top = percent(zy, pageH);
    zone.style.width = percent(zw, pageW);
    zone.style.height = percent(zh, pageH);
    zone.setAttribute(
      "aria-label",
      `Pregunta ${question.number}, opción ${option.letter}`
    );
    if (option.text) zone.title = `${option.letter}) ${option.text}`;

    const box = document.createElement("span");
    box.className = "option-box";
    const centerX = x + w / 2;
    const centerY = y + h / 2;
    box.style.left = percent(centerX - zx, zw);
    box.style.top = percent(centerY - zy, zh);
    zone.appendChild(box);
    overlay.appendChild(zone);
  }
}

/* --------------------------------------------------------------------------
   Estado de respuestas
   -------------------------------------------------------------------------- */

function questionById(qid) {
  return state.exam?.questions.find((question) => question.id === qid) || null;
}

function selectedFor(qid) {
  return state.answers[qid] || [];
}

function selectOption(qid, letter) {
  const question = questionById(qid);
  if (!question) return;
  const current = selectedFor(qid);
  let next;

  if (question.multi) {
    next = current.includes(letter)
      ? current.filter((value) => value !== letter)
      : [...current, letter];
  } else {
    next = current.includes(letter) ? [] : [letter];
  }

  if (next.length) state.answers[qid] = next.sort();
  else delete state.answers[qid];

  if (state.corrected) {
    state.corrected = false;
    state.result = null;
    showToast("Respuestas modificadas. Pulsa Corregir para actualizar la nota.");
  }

  saveProgress();
  updateAll();
}

function updateAll() {
  updateOptionClasses();
  updatePanel();
  updateProgress();
  updateToolbar();
}

function updateOptionClasses() {
  if (!state.exam) return;
  const resultMap = new Map(
    (state.result?.details || []).map((detail) => [detail.qid, detail])
  );

  $$(".option-zone").forEach((zone) => {
    const qid = zone.dataset.q;
    const letter = zone.dataset.letter;
    const question = questionById(qid);
    if (!question) return;
    const selected = selectedFor(qid).includes(letter);
    const correct = question.answer.includes(letter);

    zone.classList.toggle("selected", selected);
    zone.classList.remove("correct", "wrong", "missed");

    if (state.corrected && resultMap.has(qid)) {
      if (correct && selected) zone.classList.add("correct");
      else if (correct && !selected) zone.classList.add("missed");
      else if (!correct && selected) zone.classList.add("wrong");
    }
  });
}

function updatePanel() {
  const panel = $("#panel-scroll");
  if (!panel || !state.exam?.interactive) return;

  const scrollTop = panel.scrollTop;
  const resultMap = new Map(
    (state.result?.details || []).map((detail) => [detail.qid, detail])
  );
  const temarioAvailable =
    state.exam.subject === "ssdd" && Boolean(state.temario?.decks?.length);

  panel.innerHTML = state.exam.questions
    .map((question) => {
      const selected = selectedFor(question.id);
      const detail = resultMap.get(question.id);
      let dotClass = "";
      if (state.corrected && detail) {
        dotClass = detail.correct ? "ok" : detail.blank ? "blank" : "bad";
      } else if (selected.length) {
        dotClass = "ok";
      }

      const options = question.options
        .map((option) => {
          const isSelected = selected.includes(option.letter);
          const isCorrect = question.answer.includes(option.letter);
          let classes = isSelected ? "sel" : "";
          if (state.corrected && detail) {
            if (isCorrect && isSelected) classes = "correct";
            else if (!isCorrect && isSelected) classes = "wrong";
            else if (isCorrect && !isSelected) classes = "missed";
          }
          return `<button
            type="button"
            class="q-opt ${classes}"
            data-q="${question.id}"
            data-letter="${option.letter}"
            aria-label="Pregunta ${escapeHtml(question.number)} opción ${option.letter}"
            ${isSelected ? 'aria-pressed="true"' : 'aria-pressed="false"'}
          >${option.letter}</button>`;
        })
        .join("");

      return `
        <div class="q-row" id="panel-${question.id}">
          <button class="q-row-head" type="button" data-scroll="${question.id}">
            <span class="q-num">${escapeHtml(question.number)}</span>
            <span class="q-pts">${formatPoints(question.points)}p</span>
            ${question.multi ? '<span class="q-multi">múltiple</span>' : ""}
            <span class="q-dot ${dotClass}"></span>
          </button>
          <div class="q-text">${escapeHtml(question.text || `Pregunta ${question.number}`)}</div>
          <div class="q-options">${options}</div>
          ${
            temarioAvailable
              ? `<button class="q-temario" type="button" data-temario="${question.id}">
                  <span aria-hidden="true">▤</span> Temario
                </button>`
              : ""
          }
        </div>`;
    })
    .join("");

  panel.scrollTop = scrollTop;
}

function updateProgress() {
  if (!state.exam?.interactive) return;
  const total = state.exam.questionCount;
  const answered = state.exam.questions.filter(
    (question) => selectedFor(question.id).length > 0
  ).length;
  const text = $("#progress-text");
  const pct = $("#progress-pct");
  const bar = $("#progress-bar");
  const panelCount = $("#panel-count");
  if (text) {
    text.textContent = state.corrected && state.result
      ? `Corregido · ${state.result.correct} de ${total} correctas`
      : `${answered} de ${total} respondidas`;
  }
  if (pct) pct.textContent = `${Math.round((answered / total) * 100)}%`;
  if (bar) bar.style.width = percent(answered, total);
  if (panelCount) panelCount.textContent = `${answered} / ${total}`;
}

function updateToolbar() {
  if (!state.exam?.interactive) return;
  const button = $("#btn-correct");
  if (button) {
    button.textContent = state.corrected ? "Ver resultado" : "Corregir";
    button.classList.toggle("primary", !state.corrected);
    button.classList.toggle("green", state.corrected);
  }
  const reset = $("#btn-reset");
  if (reset) {
    reset.disabled =
      Object.keys(state.answers).length === 0 && !state.corrected;
  }
  const history = $("#btn-history");
  if (history) {
    history.hidden = state.attempts.length === 0;
    history.textContent =
      state.attempts.length > 1
        ? `Historial (${state.attempts.length})`
        : "Historial";
  }
}

function scrollToQuestion(qid) {
  if (!qid) return;
  const zone = document.querySelector(
    `.option-zone[data-q="${CSS.escape(qid)}"]`
  );
  if (!zone) return;
  const page = zone.closest(".pdf-page");
  zone.scrollIntoView({ behavior: "smooth", block: "center" });
  if (page) {
    page.classList.remove("page-highlight");
    // Reinicia la animación si se pulsa varias veces.
    void page.offsetWidth;
    page.classList.add("page-highlight");
    setTimeout(() => page.classList.remove("page-highlight"), 1700);
  }
}

function setZoom(value) {
  state.zoom = Math.max(1, Math.min(2.5, Math.round(value * 100) / 100));
  applyZoom();
}

function applyZoom() {
  const documentEl = $("#document");
  if (documentEl) {
    documentEl.style.setProperty("--pdf-zoom", String(state.zoom));
  }
  const label = $("#zoom-label");
  if (label) label.textContent = `${Math.round(state.zoom * 100)}%`;
}

/* --------------------------------------------------------------------------
   Corrección
   -------------------------------------------------------------------------- */

function gradeExam() {
  const exam = state.exam;
  if (!exam) return null;
  const penalty = exam.penalty || { type: "none" };
  const details = [];
  let rawScore = 0;
  let correct = 0;
  let wrong = 0;
  let blank = 0;

  for (const question of exam.questions) {
    const selected = selectedFor(question.id).slice().sort();
    const answer = question.answer.slice().sort();
    const isBlank = selected.length === 0;
    const isCorrect =
      !isBlank &&
      selected.length === answer.length &&
      selected.every((letter, index) => letter === answer[index]);

    if (isBlank) blank += 1;
    else if (isCorrect) {
      correct += 1;
      rawScore += question.points;
    } else {
      wrong += 1;
    }

    details.push({
      qid: question.id,
      number: question.number,
      selected,
      answer,
      blank: isBlank,
      correct: isCorrect,
      points: question.points,
      optionCount: question.options.length,
    });
  }

  let penaltyPoints = 0;
  if (penalty.type === "fraction") {
    for (const detail of details) {
      if (!detail.blank && !detail.correct) {
        penaltyPoints += detail.points * (penalty.fraction || 0);
      }
    }
  } else if (penalty.type === "groups") {
    const eligible = details.filter(
      (detail) =>
        !detail.blank &&
        !detail.correct &&
        (penalty.maxOptions == null ||
          detail.optionCount <= penalty.maxOptions)
    );
    penaltyPoints =
      Math.floor(eligible.length / (penalty.n || 3)) * (penalty.points || 1);
  } else if (penalty.type === "perWrong") {
    penaltyPoints = wrong * (penalty.points || 0);
  }

  const score = Math.max(0, rawScore - penaltyPoints);
  const maxScore = exam.maxScore || 0;
  const percentage = maxScore ? (score / maxScore) * 100 : 0;

  return {
    details,
    rawScore,
    penaltyPoints,
    score,
    maxScore,
    percentage,
    correct,
    wrong,
    blank,
    answered: exam.questionCount - blank,
    penalty,
  };
}

function correctNow() {
  if (!state.exam?.interactive) return;
  const unanswered = state.exam.questions.filter(
    (question) => selectedFor(question.id).length === 0
  ).length;

  const apply = () => {
    state.corrected = true;
    state.result = gradeExam();
    if (state.result?.answered > 0) {
      recordAttempt(state.result);
    }
    saveProgress();
    updateAll();
    showResultModal();
  };

  if (unanswered > 0) {
    showConfirm({
      title: "Quedan preguntas sin responder",
      message: `Hay ${unanswered} ${
        unanswered === 1 ? "pregunta" : "preguntas"
      } sin responder. Las preguntas en blanco no suman puntos, pero tampoco restan. ¿Quieres corregir igualmente?`,
      confirmLabel: "Corregir",
      onConfirm: apply,
    });
  } else {
    apply();
  }
}

function scoreNote(result) {
  const notes = [];
  const exam = state.exam;
  if (exam.scoreScale) {
    notes.push(
      `La puntuación por pregunta se ha normalizado al total del examen (${formatPoints(
        exam.declaredTotal
      )} puntos).`
    );
  }
  if (
    exam.declaredTotal &&
    exam.declaredTotal - exam.maxScore > 0.01
  ) {
    notes.push(
      `Solo se corrigen las preguntas tipo test (${formatPoints(
        exam.maxScore
      )} puntos). El examen completo vale ${formatPoints(
        exam.declaredTotal
      )} puntos.`
    );
  }
  if (result.penaltyPoints > 0.001) {
    notes.push(`Penalización aplicada: ${result.penalty.text}`);
  }
  if (!notes.length) {
    notes.push("Puntuación calculada sobre las preguntas tipo test corregibles.");
  }
  return notes.join(" ");
}

function scoreLabel(percentage) {
  if (percentage >= 90) return "Excelente";
  if (percentage >= 75) return "Muy bien";
  if (percentage >= 60) return "Bien";
  if (percentage >= 50) return "Aprobado";
  if (percentage >= 35) return "A repasar";
  return "Hay que repasar";
}

function showResultModal() {
  if (!state.result) {
    state.result = gradeExam();
    if (!state.result) return;
  }
  closeModal();
  const result = state.result;
  const percentage = Math.round(result.percentage);
  const ringColor =
    percentage >= 60 ? "#15803d" : percentage >= 40 ? "#b45309" : "#dc2626";
  const bestAttempt = state.attempts.length
    ? Math.max(...state.attempts.map((attempt) => attempt.percentage))
    : null;
  const attemptNote = state.attempts.length
    ? `<p class="attempt-note">
        ${plural(state.attempts.length, "intento guardado", "intentos guardados")}
        · mejor ${Math.round(bestAttempt)}%
      </p>`
    : "";
  const rows = result.details
    .map((detail) => {
      const status = detail.correct
        ? '<span class="r-status ok">✓</span>'
        : detail.blank
          ? '<span class="r-status blank">–</span>'
          : '<span class="r-status bad">✕</span>';
      const selected = detail.selected.length
        ? detail.selected.join(", ")
        : "—";
      const answer = detail.answer.join(", ");
      return `
        <button class="result-row" type="button" data-scroll-result="${detail.qid}">
          <span class="r-num">${escapeHtml(detail.number)}</span>
          ${status}
          <span class="r-answer">Tu respuesta: <b>${escapeHtml(selected)}</b></span>
          <span class="${detail.correct ? "r-correct" : "r-wrong"}">
            Correcta: ${escapeHtml(answer)}
          </span>
          <span class="r-points">${detail.correct ? `+${formatPoints(detail.points)}` : "0"} p</span>
        </button>`;
    })
    .join("");

  const modal = document.createElement("div");
  modal.className = "modal-backdrop";
  modal.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="result-title">
      <button class="modal-close" type="button" aria-label="Cerrar">×</button>
      <h2 id="result-title">Resultado</h2>
      <p class="modal-sub">
        ${escapeHtml(state.exam.codeLabel)} · ${escapeHtml(state.exam.subjectName)}
        · ${escapeHtml(state.exam.year || "")}
      </p>

      <div class="score-hero">
        <div class="score-ring" style="--pct:${Math.max(
          0,
          Math.min(100, percentage)
        )};--ring-color:${ringColor}">
          <div class="score-ring-inner">
            <strong>${percentage}%</strong>
            <span>aciertos</span>
          </div>
        </div>
        <div class="score-copy">
          <h3>${formatPoints(result.score)} / ${formatPoints(result.maxScore)} puntos</h3>
          <p>
            ${result.correct} correctas · ${result.wrong} incorrectas · ${result.blank} en blanco
          </p>
          <span class="score-label">${scoreLabel(percentage)}</span>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat ok"><strong>${result.correct}</strong><span>Correctas</span></div>
        <div class="stat bad"><strong>${result.wrong}</strong><span>Incorrectas</span></div>
        <div class="stat"><strong>${result.blank}</strong><span>En blanco</span></div>
        <div class="stat warn"><strong>${result.penaltyPoints > 0.001 ? `−${formatPoints(result.penaltyPoints)}` : "0"}</strong><span>Penalización</span></div>
      </div>

      <p class="score-note">${escapeHtml(scoreNote(result))}</p>
      ${attemptNote}

      <div class="result-list">${rows}</div>

      <div class="modal-actions">
        ${
          result.correct < result.details.length
            ? `<button class="btn ghost" type="button" id="review-failures">Repasar fallos</button>`
            : ""
        }
        ${
          state.attempts.length
            ? `<button class="btn ghost" type="button" id="result-history">Historial</button>`
            : ""
        }
        <button class="btn ghost" type="button" id="retry-exam">Reintentar</button>
        <button class="btn primary" type="button" id="close-result">Cerrar</button>
      </div>
    </div>`;

  document.body.appendChild(modal);
  document.body.style.overflow = "hidden";
  modal.querySelector(".modal-close")?.focus();

  const close = () => closeModal();
  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });
  modal.querySelector(".modal-close")?.addEventListener("click", close);
  modal.querySelector("#close-result")?.addEventListener("click", close);
  modal.querySelector("#retry-exam")?.addEventListener("click", () => {
    close();
    resetAnswers();
  });
  modal.querySelector("#result-history")?.addEventListener("click", () => {
    close();
    showHistoryModal();
  });
  modal.querySelector("#review-failures")?.addEventListener("click", () => {
    const first = result.details.find((detail) => !detail.correct);
    close();
    if (first) setTimeout(() => scrollToQuestion(first.qid), 80);
  });
  $$("[data-scroll-result]", modal).forEach((button) => {
    button.addEventListener("click", () => {
      const qid = button.dataset.scrollResult;
      close();
      setTimeout(() => scrollToQuestion(qid), 80);
    });
  });
}

function showHistoryModal() {
  if (!state.exam || !state.attempts.length) {
    showToast("Todavía no hay intentos guardados.");
    return;
  }
  closeModal();
  const best = Math.max(
    ...state.attempts.map((attempt) => attempt.percentage)
  );
  const rows = [...state.attempts]
    .reverse()
    .map((attempt, index) => {
      const number = state.attempts.length - index;
      const passed = attempt.percentage >= PASS_PERCENTAGE;
      return `
        <article class="history-row ${passed ? "passed" : ""}">
          <div class="history-main">
            <strong>Intento ${number}</strong>
            <span>${escapeHtml(formatAttemptDate(attempt.at))}</span>
          </div>
          <div class="history-score">
            <strong>${Math.round(attempt.percentage)}%</strong>
            <span>${formatPoints(attempt.score)} / ${formatPoints(attempt.maxScore)} pts</span>
          </div>
          <span class="history-badge ${passed ? "ok" : "bad"}">
            ${passed ? "Aprobado" : "Suspenso"}
          </span>
          <span class="history-detail">
            ${attempt.correct} aciertos · ${attempt.wrong} fallos · ${attempt.blank} en blanco
          </span>
        </article>`;
    })
    .join("");

  const modal = document.createElement("div");
  modal.className = "modal-backdrop";
  modal.innerHTML = `
    <div class="modal history-modal" role="dialog" aria-modal="true" aria-labelledby="history-title">
      <button class="modal-close" type="button" aria-label="Cerrar">×</button>
      <h2 id="history-title">Historial de intentos</h2>
      <p class="modal-sub">
        ${escapeHtml(state.exam.codeLabel)} · ${escapeHtml(state.exam.subjectName)}
        · ${plural(state.attempts.length, "intento", "intentos")} · mejor ${Math.round(best)}%
      </p>
      <div class="history-list">${rows}</div>
      <div class="modal-actions">
        <button class="btn primary" type="button" id="close-history">Cerrar</button>
      </div>
    </div>`;

  document.body.appendChild(modal);
  document.body.style.overflow = "hidden";
  modal.querySelector(".modal-close")?.focus();

  const close = () => closeModal();
  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });
  modal.querySelector(".modal-close")?.addEventListener("click", close);
  modal.querySelector("#close-history")?.addEventListener("click", close);
}

function showConfirm({ title, message, confirmLabel, onConfirm }) {
  closeModal();
  const modal = document.createElement("div");
  modal.className = "modal-backdrop";
  modal.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title" style="width:min(480px,100%)">
      <button class="modal-close" type="button" aria-label="Cerrar">×</button>
      <h2 id="confirm-title">${escapeHtml(title)}</h2>
      <p class="modal-message">${escapeHtml(message)}</p>
      <div class="modal-actions">
        <button class="btn ghost" type="button" id="confirm-cancel">Cancelar</button>
        <button class="btn primary" type="button" id="confirm-ok">${escapeHtml(confirmLabel)}</button>
      </div>
    </div>`;
  document.body.appendChild(modal);
  document.body.style.overflow = "hidden";
  modal.querySelector(".modal-close")?.focus();

  const close = () => closeModal();
  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });
  modal.querySelector(".modal-close")?.addEventListener("click", close);
  modal.querySelector("#confirm-cancel")?.addEventListener("click", close);
  modal.querySelector("#confirm-ok")?.addEventListener("click", () => {
    close();
    onConfirm();
  });
}

function temarioDeck(deckId) {
  return (
    state.temario?.decks?.find((deck) => deck.id === deckId) || null
  );
}

function temarioUrl(deck) {
  return new URL(deck.file, document.baseURI).href;
}

async function loadTemarioDoc(deck) {
  if (state.temarioDocs.has(deck.id)) {
    return state.temarioDocs.get(deck.id);
  }
  const task = pdfjsLib.getDocument({
    url: temarioUrl(deck),
    cMapUrl: CMAP_URL,
    cMapPacked: true,
    standardFontDataUrl: STANDARD_FONTS_URL,
  });
  const doc = await task.promise;
  state.temarioDocs.set(deck.id, doc);
  return doc;
}

function openTemario(qid) {
  if (!state.temario?.decks?.length) {
    showToast("El temario no está disponible.");
    return;
  }

  const question = qid ? questionById(qid) : null;
  const info = question
    ? state.temario.questions?.[`${state.exam.id}::${question.id}`]
    : null;
  const suggestions = Array.isArray(info?.slides) ? info.slides : [];
  const firstSuggestion = suggestions[0] || null;
  // Si no hay sugerencias, empieza por el primer tema para poder explorar el
  // temario completo; el tema detectado puede ser poco fiable sin diapositivas.
  let currentDeckId = firstSuggestion?.deck || state.temario.decks[0].id;
  if (!temarioDeck(currentDeckId)) {
    currentDeckId = state.temario.decks[0].id;
  }
  let currentPage =
    firstSuggestion?.deck === currentDeckId ? firstSuggestion.page : 1;

  closeModal();
  state.temarioToken += 1;
  const modal = document.createElement("div");
  modal.className = "modal-backdrop";
  modal.innerHTML = `
    <div class="modal temario-modal" role="dialog" aria-modal="true" aria-labelledby="temario-title">
      <button class="modal-close" type="button" aria-label="Cerrar">×</button>
      <h2 id="temario-title">Temario de Sistemas Distribuidos</h2>
      <p class="modal-sub">
        ${
          question
            ? `Pregunta ${escapeHtml(question.number)} · ${escapeHtml(
                state.exam.codeLabel
              )}`
            : "Explora las diapositivas del temario"
        }
      </p>
      ${
        question
          ? `<p class="temario-question">${escapeHtml(question.text)}</p>`
          : ""
      }
      <p class="temario-hint">
        Las sugerencias se generan automáticamente a partir del temario.
        Puedes cambiar de tema o de página para buscar la explicación exacta.
      </p>

      <div class="temario-layout">
        <aside class="temario-side">
          <div class="temario-side-head">
            <h3>Diapositivas sugeridas</h3>
            <span>${suggestions.length ? plural(suggestions.length, "coincidencia", "coincidencias") : "Sin coincidencias claras"}</span>
          </div>
          <div class="temario-suggestions" id="temario-suggestions">
            ${
              suggestions.length
                ? suggestions
                    .map((slide) => {
                      const deck = temarioDeck(slide.deck);
                      const active =
                        slide.deck === currentDeckId && slide.page === currentPage;
                      return `<button
                        class="temario-suggestion ${active ? "active" : ""}"
                        type="button"
                        data-deck="${escapeHtml(slide.deck)}"
                        data-page="${slide.page}"
                      >
                        <span>${escapeHtml(deck?.title || slide.deck)}</span>
                        <strong>${escapeHtml(
                          slide.title || `Diapositiva ${slide.page}`
                        )}</strong>
                        <small>p. ${slide.page}</small>
                      </button>`;
                    })
                    .join("")
                : `<p class="temario-empty">
                    No hay coincidencias claras para esta pregunta en los
                    cuatro temas actuales. Puedes explorar el temario completo
                    con el selector de tema.
                  </p>`
            }
          </div>

          <label class="temario-deck-label">
            <span>Tema</span>
            <select id="temario-deck">
              ${state.temario.decks
                .map(
                  (deck) =>
                    `<option value="${escapeHtml(deck.id)}">${escapeHtml(
                      deck.title
                    )}</option>`
                )
                .join("")}
            </select>
          </label>

          <div class="temario-pages" id="temario-pages"></div>
        </aside>

        <section class="temario-main">
          <div class="temario-viewer" id="temario-viewer">
            <div class="pdf-loading">
              <span class="spinner"></span> Cargando diapositiva…
            </div>
          </div>
          <div class="temario-controls">
            <button class="btn ghost small" id="temario-prev" type="button">
              ← Anterior
            </button>
            <span id="temario-page-label"></span>
            <button class="btn ghost small" id="temario-next" type="button">
              Siguiente →
            </button>
            <a class="btn ghost small" id="temario-open" target="_blank" rel="noopener">
              Abrir PDF
            </a>
          </div>
        </section>
      </div>
    </div>`;

  document.body.appendChild(modal);
  document.body.style.overflow = "hidden";
  modal.querySelector(".modal-close")?.focus();

  const viewer = $("#temario-viewer", modal);
  const pagesEl = $("#temario-pages", modal);
  const deckSelect = $("#temario-deck", modal);
  const pageLabel = $("#temario-page-label", modal);
  const prevButton = $("#temario-prev", modal);
  const nextButton = $("#temario-next", modal);
  const openLink = $("#temario-open", modal);
  const suggestionsEl = $("#temario-suggestions", modal);

  const currentDeck = () =>
    temarioDeck(currentDeckId) || state.temario.decks[0];

  const clampPage = (page, deck) =>
    Math.max(1, Math.min(deck.pages, Number(page) || 1));

  const renderChrome = () => {
    const deck = currentDeck();
    currentPage = clampPage(currentPage, deck);
    deckSelect.value = deck.id;
    pageLabel.textContent = `Diapositiva ${currentPage} de ${deck.pages}`;
    prevButton.disabled = currentPage <= 1;
    nextButton.disabled = currentPage >= deck.pages;
    openLink.href = `${temarioUrl(deck)}#page=${currentPage}`;

    suggestionsEl.querySelectorAll("[data-deck]").forEach((button) => {
      button.classList.toggle(
        "active",
        button.dataset.deck === deck.id &&
          Number(button.dataset.page) === currentPage
      );
    });

    const pagesScroll = pagesEl.scrollTop;
    pagesEl.innerHTML = deck.slides
      .map(
        (slide) => `<button
          class="temario-page ${slide.page === currentPage ? "active" : ""}"
          type="button"
          data-page="${slide.page}"
        >
          <span>${slide.page}</span>
          ${escapeHtml(slide.title || `Diapositiva ${slide.page}`)}
        </button>`
      )
      .join("");
    pagesEl.scrollTop = pagesScroll;
  };

  const renderPage = async () => {
    const deck = currentDeck();
    currentPage = clampPage(currentPage, deck);
    renderChrome();
    const token = ++state.temarioToken;
    viewer.innerHTML = `
      <div class="pdf-loading">
        <span class="spinner"></span> Cargando diapositiva…
      </div>`;

    try {
      const doc = await loadTemarioDoc(deck);
      if (token !== state.temarioToken || !document.body.contains(modal)) return;
      const page = await doc.getPage(currentPage);
      if (token !== state.temarioToken || !document.body.contains(modal)) return;

      const baseViewport = page.getViewport({ scale: 1 });
      const availableWidth = Math.max(
        240,
        Math.min(viewer.clientWidth || 760, 1100)
      );
      const viewport = page.getViewport({
        scale: availableWidth / baseViewport.width,
      });
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.floor(viewport.width * dpr));
      canvas.height = Math.max(1, Math.floor(viewport.height * dpr));
      canvas.style.width = "100%";
      canvas.style.height = "auto";
      const context = canvas.getContext("2d", { alpha: false });
      viewer.innerHTML = "";
      viewer.appendChild(canvas);
      await page.render({
        canvasContext: context,
        viewport,
        transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null,
      }).promise;
    } catch (error) {
      if (token !== state.temarioToken) return;
      viewer.innerHTML = `
        <div class="temario-error">
          No se pudo cargar esta diapositiva. Puedes abrir el PDF original.
        </div>`;
      console.error(error);
    }
  };

  const setDeck = (deckId, page = 1) => {
    const deck = temarioDeck(deckId);
    if (!deck) return;
    currentDeckId = deck.id;
    currentPage = clampPage(page, deck);
    renderPage();
  };

  const setPage = (page) => {
    currentPage = clampPage(page, currentDeck());
    renderPage();
  };

  modal.addEventListener("click", (event) => {
    if (event.target === modal) closeModal();
  });
  modal.querySelector(".modal-close")?.addEventListener("click", closeModal);
  deckSelect.addEventListener("change", () => setDeck(deckSelect.value, 1));
  prevButton.addEventListener("click", () => setPage(currentPage - 1));
  nextButton.addEventListener("click", () => setPage(currentPage + 1));
  pagesEl.addEventListener("click", (event) => {
    const button = event.target.closest("[data-page]");
    if (button) setPage(Number(button.dataset.page));
  });
  suggestionsEl.addEventListener("click", (event) => {
    const button = event.target.closest("[data-deck]");
    if (button) setDeck(button.dataset.deck, Number(button.dataset.page));
  });

  renderPage();
}

function closeModal() {
  $$(".modal-backdrop").forEach((modal) => modal.remove());
  document.body.style.overflow = "";
}

function resetAnswers() {
  if (!state.exam?.interactive) return;
  const hasAnswers = Object.keys(state.answers).length > 0;
  if (!hasAnswers && !state.corrected) {
    showToast("No hay respuestas que borrar.");
    return;
  }
  showConfirm({
    title: "Reiniciar examen",
    message:
      "Se borrarán tus respuestas actuales y el resultado en pantalla. El historial de intentos se conserva.",
    confirmLabel: "Reiniciar",
    onConfirm: () => {
      state.answers = {};
      state.corrected = false;
      state.result = null;
      saveProgress();
      updateAll();
      showToast("Examen reiniciado.");
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
  });
}

/* --------------------------------------------------------------------------
   Panel móvil
   -------------------------------------------------------------------------- */

function togglePanel() {
  if (state.panelOpen) closePanel();
  else openPanel();
}

function openPanel() {
  const panel = $("#answers-panel");
  const backdrop = $("#panel-backdrop");
  if (!panel) return;
  state.panelOpen = true;
  panel.classList.add("open");
  // En escritorio la hoja de respuestas ya está visible; el fondo modal solo
  // se necesita cuando el panel se convierte en cajón inferior en móvil.
  if (backdrop) {
    backdrop.hidden = !window.matchMedia("(max-width: 960px)").matches;
  }
}

function closePanel() {
  const panel = $("#answers-panel");
  const backdrop = $("#panel-backdrop");
  state.panelOpen = false;
  panel?.classList.remove("open");
  if (backdrop) backdrop.hidden = true;
}

/* --------------------------------------------------------------------------
   Inicio
   -------------------------------------------------------------------------- */

init();
