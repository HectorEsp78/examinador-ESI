"""Genera app/data/ssdd_explicaciones.json para el repaso de preguntas falladas.

Para cada pregunta de SSDD con una diapositiva sugerida suficientemente fiable
(ver app/data/ssdd_temario.json), extrae las líneas de esa diapositiva que más se
parecen a la pregunta y a su respuesta correcta. Es un extracto literal del
temario: no redacta texto nuevo. Si no hay coincidencia fiable, la pregunta no
aparece en el fichero y la app indica que no hay explicación disponible.

Requiere haber ejecutado antes tools/build_temario.py y tener poppler-utils.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_temario as temario  # noqa: E402  (construye el índice al importarse)

ROOT = temario.ROOT
OUT = ROOT / "app/data/ssdd_explicaciones.json"

MIN_SLIDE_SCORE = 25  # por debajo, la sugerencia suele ser solo temática
MIN_LINE_SCORE = 6.0  # peso idf mínimo para considerar relevante una línea
MAX_LINES = 2
MAX_CHARS = 420

FOOTER = re.compile(
    r"Version \d|Distributed Systems ::|Instructor.s Guide|David\.Villa|Pearson|©|"
    r"^\d+(\s+\d+)*$|https?://\S+$"
)
BULLET = re.compile(r"^[●•▪◦○■\-–*]+\.?\s*")
CODE_LIKE = re.compile(r"\w\.\w+\(|\w\(\)|[{}=]|→|^\d+\.?\s|Not applicable")


def slide_lines(text, title):
    """Devuelve las viñetas de la diapositiva, uniendo las líneas partidas."""
    items = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or FOOTER.search(line):
            continue
        is_bullet = bool(BULLET.match(line))
        line = BULLET.sub("", line).strip()
        if not line:
            continue
        if items and not is_bullet and line[0].islower():
            items[-1] += " " + line
        else:
            items.append(line)
    title_norm = temario.normalize(title)
    return [
        item
        for item in items
        if is_prose(item) and temario.normalize(item) not in title_norm
    ]


def is_prose(line):
    """Descarta restos de diagramas y código, que no explican nada por sí solos."""
    words = line.split()
    if len(words) < 5 or line.endswith(":") or CODE_LIKE.search(line):
        return False
    alpha = sum(len(word) for word in words if word.isalpha())
    return alpha / len(line) >= 0.6


def excerpt_for(question, lines):
    correct = [o.get("text", "") for o in question["options"] if o.get("correct")]
    answer_tokens = set(temario.tokens(" ".join(correct)))
    query_tokens = set(temario.tokens(question["text"])) | answer_tokens

    scored = []
    for index, line in enumerate(lines):
        line_tokens = set(temario.tokens(line))
        answer_score = sum(temario.idf.get(t, 1.0) for t in line_tokens & answer_tokens)
        score = answer_score + sum(
            temario.idf.get(t, 1.0) for t in line_tokens & query_tokens
        )
        if score >= MIN_LINE_SCORE:
            scored.append((score, index, answer_score))

    # Una línea que no toca la respuesta correcta no sirve para justificarla.
    if not any(answer_score > 0 for _, _, answer_score in scored):
        return []

    chosen = sorted(index for _, index, _ in sorted(scored, reverse=True)[:MAX_LINES])
    out, used = [], 0
    for index in chosen:
        if used + len(lines[index]) > MAX_CHARS and out:
            break
        out.append(lines[index][:MAX_CHARS])
        used += len(lines[index])
    return out


def main():
    catalog = json.load(open(ROOT / "app/data/exams.json", encoding="utf-8"))
    index = json.load(open(ROOT / "app/data/ssdd_temario.json", encoding="utf-8"))
    pages = {deck: temario.pdf_pages(deck) for deck, _ in temario.DECKS}

    explanations = {}
    total = 0
    for exam in catalog["exams"]:
        if exam.get("subject") != "ssdd":
            continue
        for question in exam.get("questions", []):
            total += 1
            key = f"{exam['id']}::{question['id']}"
            for slide in index["questions"].get(key, {}).get("slides", [])[:2]:
                if slide["score"] < MIN_SLIDE_SCORE:
                    continue
                text = pages[slide["deck"]][slide["page"] - 1]
                excerpt = excerpt_for(question, slide_lines(text, slide["title"]))
                if excerpt:
                    explanations[key] = {
                        "deck": slide["deck"],
                        "page": slide["page"],
                        "excerpt": excerpt,
                    }
                    break

    OUT.write_text(
        json.dumps(explanations, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"Explicaciones: {len(explanations)} de {total} preguntas de SSDD → {OUT}")


if __name__ == "__main__":
    main()
