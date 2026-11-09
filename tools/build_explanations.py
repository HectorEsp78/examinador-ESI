"""Genera app/data/ssdd_explicaciones.json para el repaso de preguntas falladas.

Las explicaciones están redactadas en tools/ssdd_explicaciones_redactadas.json,
indexadas por una huella del enunciado, las opciones y la solución. Así, una misma
pregunta repetida en varios exámenes comparte explicación, y esta se conserva al
regenerar el catálogo. Si una pregunta cambia, su huella cambia y queda sin
explicación hasta que se redacte de nuevo.

Cada pregunta enlaza además con la diapositiva sugerida en ssdd_temario.json, si
la coincidencia es suficientemente fiable.
"""

import hashlib
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRITTEN = ROOT / "tools/ssdd_explicaciones_redactadas.json"
OUT = ROOT / "app/data/ssdd_explicaciones.json"

MIN_SLIDE_SCORE = 25  # por debajo, la sugerencia suele ser solo temática


def normalize(text):
    text = unicodedata.normalize("NFD", text or "").lower()
    return re.sub(r"\W+", " ", text).strip()


def fingerprint(question):
    options = sorted(
        (normalize(option.get("text")), bool(option.get("correct")))
        for option in question["options"]
    )
    payload = json.dumps([normalize(question["text"]), options], ensure_ascii=False)
    return hashlib.sha1(payload.encode()).hexdigest()[:10]


def main():
    catalog = json.loads((ROOT / "app/data/exams.json").read_text(encoding="utf-8"))
    index = json.loads((ROOT / "app/data/ssdd_temario.json").read_text(encoding="utf-8"))
    written = json.loads(WRITTEN.read_text(encoding="utf-8"))

    explanations = {}
    total = 0
    used = set()
    for exam in catalog["exams"]:
        if exam.get("subject") != "ssdd" or not exam.get("interactive"):
            continue
        for question in exam["questions"]:
            total += 1
            print_key = fingerprint(question)
            text = written.get(print_key)
            if not text:
                continue
            used.add(print_key)
            key = f"{exam['id']}::{question['id']}"
            entry = {"text": text}
            slides = index["questions"].get(key, {}).get("slides", [])
            if slides and slides[0]["score"] >= MIN_SLIDE_SCORE:
                entry["deck"] = slides[0]["deck"]
                entry["page"] = slides[0]["page"]
            explanations[key] = entry

    OUT.write_text(
        json.dumps(explanations, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"Explicaciones: {len(explanations)} de {total} preguntas de SSDD → {OUT}")
    unused = len(written) - len(used)
    if unused:
        print(f"Aviso: {unused} explicaciones ya no corresponden a ninguna pregunta.")


if __name__ == "__main__":
    main()
