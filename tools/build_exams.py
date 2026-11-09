#!/usr/bin/env python3
"""Genera el catálogo y los datos interactivos de la app a partir de past-exams/.

Uso:
    python3 tools/build_exams.py

Salida:
    app/data/exams.json
    app/pdfs/*.pdf

Requiere poppler-utils (pdftohtml, pdftotext).
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "past-exams"
APP = ROOT / "app"
OUT_PDFS = APP / "pdfs"
OUT_DATA = APP / "data" / "exams.json"

SUBJECTS = {
    "redes1": "Redes I",
    "redes2": "Redes II",
    "ssdd": "Sistemas Distribuidos",
}

SUBJECT_ORDER = {"redes1": 0, "redes2": 1, "ssdd": 2}

MARKERS = {"\u25a1", "\u25a0", "\x03", "\x04"}
FILLED = {"\u25a0", "\x04"}


# ---------------------------------------------------------------------------
# Extracción de texto / coordenadas
# ---------------------------------------------------------------------------


def run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Error ejecutando {' '.join(cmd)}:\n{res.stderr}")
    return res.stdout


def clean_text(raw: str) -> str:
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()


def xml_pages(path: Path) -> list[dict[str, Any]]:
    """Texto y cajas que devuelve pdftohtml. Coordenadas en puntos PDF."""
    out = run(
        [
            "pdftohtml",
            "-xml",
            "-i",
            "-zoom",
            "1",
            "-noroundcoord",
            "-stdout",
            "-q",
            str(path),
        ]
    )
    pages: list[dict[str, Any]] = []
    all_fonts: dict[str, dict[str, Any]] = {}
    for pm in re.finditer(
        r'<page number="(\d+)"[^>]*height="([\d.]+)" width="([\d.]+)"[^>]*>(.*?)</page>',
        out,
        re.S,
    ):
        num, height, width, body = pm.groups()
        for fm in re.finditer(
            r'<fontspec id="(\d+)" size="([\d.]+)" family="([^"]+)" color="([^"]+)"',
            body,
        ):
            all_fonts[fm.group(1)] = {
                "size": float(fm.group(2)),
                "family": fm.group(3),
                "color": fm.group(4),
            }
        items: list[dict[str, Any]] = []
        for tm in re.finditer(
            r'<text top="([\d.]+)" left="([\d.]+)" width="([\d.]+)" height="([\d.]+)" font="(\d+)">(.*?)</text>',
            body,
            re.S,
        ):
            top, left, w, h, font, raw = tm.groups()
            items.append(
                {
                    "top": float(top),
                    "left": float(left),
                    "w": float(w),
                    "h": float(h),
                    "font": font,
                    "raw": raw,
                    "text": clean_text(raw),
                    "bold": "<b>" in raw,
                }
            )
        pages.append(
            {
                "num": int(num),
                "H": float(height),
                "W": float(width),
                "items": items,
                "fonts": all_fonts,
            }
        )
    return pages


def bbox_marker_glyphs(path: Path) -> list[list[dict[str, Any]]]:
    """Posición y carácter de los cuadros □/■ (también glifos PUA de PDFs antiguos)."""
    out = run(["pdftotext", "-bbox-layout", str(path), "-"])
    pages: list[list[dict[str, Any]]] = []
    for pm in re.finditer(
        r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', out, re.S
    ):
        _width, _height, body = pm.groups()
        markers: list[dict[str, Any]] = []
        for wm in re.finditer(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>',
            body,
            re.S,
        ):
            x0, y0, x1, y1, text = wm.groups()
            text = html.unescape(text)
            if text in MARKERS:
                markers.append(
                    {
                        "x": (float(x0) + float(x1)) / 2,
                        "y": (float(y0) + float(y1)) / 2,
                        "ch": text,
                    }
                )
        pages.append(markers)
    return pages


def page_markers(page: dict[str, Any], glyphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Localiza los cuadros de opción y decide si están marcados (solución)."""
    result: list[dict[str, Any]] = []
    for it in page["items"]:
        text = it["text"]
        ch: str | None = None
        if "\u25a1" in text or "\u25a0" in text:
            ch = "\u25a0" if "\u25a0" in text else "\u25a1"
        else:
            font = page["fonts"].get(it["font"], {})
            family = font.get("family", "")
            if (
                text == ""
                and ("MSAM" in family or "Symbol" in family)
                and 3 < it["w"] < 40
                and 3 < it["h"] < 40
            ):
                ch = None  # se resuelve con pdftotext
        if ch is None and not (
            text == ""
            and (
                "MSAM" in page["fonts"].get(it["font"], {}).get("family", "")
                or "Symbol" in page["fonts"].get(it["font"], {}).get("family", "")
            )
        ):
            continue
        # Los glifos PUA (\x03/\x04) no llegan a pdftohtml; los recuperamos
        # emparejando con la caja más cercana de pdftotext.
        best = None
        best_dist = 1e9
        cx = it["left"] + it["w"] / 2
        cy = it["top"] + it["h"] / 2
        for g in glyphs:
            dist = ((g["x"] - cx) ** 2 + (g["y"] - cy) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best = g
        if best is not None and best_dist < 10:
            ch = best["ch"]
        if ch is None:
            ch = "\u25a1"
        result.append(
            {
                "left": it["left"],
                "top": it["top"],
                "w": it["w"],
                "h": it["h"],
                "cy": cy,
                "ch": ch,
                "filled": ch in FILLED,
            }
        )
    return result


def option_letter(marker: dict[str, Any], items: list[dict[str, Any]]) -> tuple[str, str] | None:
    """Devuelve (letra, texto) de la opción situada a la derecha del cuadro."""
    candidates: list[tuple[float, str, str]] = []
    for it in items:
        if it["left"] <= marker["left"] + 1:
            continue
        cy = it["top"] + it["h"] / 2
        if abs(cy - marker["cy"]) > 5.5:
            continue
        text = it["text"]
        if not text:
            continue
        m = re.match(r"^\(?([A-Za-z])[\.\)]\s*(.*)$", text)
        if m:
            candidates.append((it["left"], m.group(1).lower(), m.group(2)))
            continue
        if re.fullmatch(r"[A-Za-z]", text):
            # En muchos PDFs la letra y el paréntesis van en cajas separadas.
            nxt = None
            for it2 in items:
                if it2["left"] > it["left"] and abs(it2["top"] + it2["h"] / 2 - cy) < 5.5:
                    if nxt is None or it2["left"] < nxt["left"]:
                        nxt = it2
            rest = ""
            if nxt:
                t2 = nxt["text"]
                m2 = re.match(r"^[\)\.]\s*(.*)$", t2)
                if m2:
                    rest = m2.group(1)
                elif t2.startswith(")"):
                    rest = t2[1:].strip()
            candidates.append((it["left"], text.lower(), rest))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    _x, letter, text = candidates[0]
    return letter, text


# ---------------------------------------------------------------------------
# Cabeceras, puntuación y metadatos
# ---------------------------------------------------------------------------


@dataclass
class Header:
    page: int
    top: float
    left: float
    kind: str  # 'question' | 'block'
    number: str
    points: float | None
    text: str
    seq: int = 0


def build_lines(page: dict[str, Any]) -> list[dict[str, Any]]:
    items = [it for it in page["items"] if it["text"]]
    items.sort(key=lambda it: (it["top"], it["left"]))
    lines: list[dict[str, Any]] = []
    for it in items:
        cy = it["top"] + it["h"] / 2
        placed = False
        for ln in lines:
            if abs(ln["cy"] - cy) <= 3.6:
                ln["items"].append(it)
                ln["cy"] = (ln["cy"] * ln["n"] + cy) / (ln["n"] + 1)
                ln["n"] += 1
                placed = True
                break
        if not placed:
            lines.append({"cy": cy, "n": 1, "items": [it]})
    for ln in lines:
        ln["items"].sort(key=lambda it: it["left"])
        ln["text"] = " ".join(it["text"] for it in ln["items"]).strip()
        ln["left"] = ln["items"][0]["left"]
        ln["top"] = min(it["top"] for it in ln["items"])
        ln["bold"] = any(it["bold"] for it in ln["items"])
    lines.sort(key=lambda ln: (ln["cy"], ln["left"]))
    return lines


POINTS_RE = re.compile(r"(?:\[|\(|\[)\s*(\d+(?:[.,]\d+)?)\s*p\s*(?:\]|\))", re.I)
QUESTION_RE = re.compile(
    r"^\s*(?:>\s*)?(\d+)\.?\s*(?:\[(\d+(?:[.,]\d+)?)\s*p\]|\((\d+(?:[.,]\d+)?)\s*p\))?\s*(.*)$",
    re.I,
)
BLOCK_RE = re.compile(
    r"^\s*([A-Z])\.?\s*(?:\[(\d+(?:[.,]\d+)?)\s*p\]|\((\d+(?:[.,]\d+)?)\s*p\))\s*(.*)$",
    re.I,
)


def extract_headers(pages: list[dict[str, Any]]) -> list[Header]:
    headers: list[Header] = []
    for pi, page in enumerate(pages):
        for ln in build_lines(page):
            text = ln["text"]
            if not text:
                continue
            # Bloques: "E. [2p] ...", "B [7p] ..."
            bm = BLOCK_RE.match(text)
            if bm:
                headers.append(
                    Header(
                        page=pi,
                        top=ln["top"],
                        left=ln["left"],
                        kind="block",
                        number=bm.group(1).upper(),
                        points=float((bm.group(2) or bm.group(3)).replace(",", ".")),
                        text=bm.group(4).strip(),
                    )
                )
                continue
            qm = QUESTION_RE.match(text)
            if not qm:
                continue
            number, p1, p2, rest = qm.groups()
            points = None
            if p1 or p2:
                points = float((p1 or p2).replace(",", "."))
            # Evitar números de línea de bloques de código: no son negrita,
            # no llevan [p] y el texto empieza en minúscula.
            if points is None:
                if not ln["bold"] and not rest.startswith(("¿", "¡")):
                    continue
                if rest and rest[0].islower():
                    continue
                if not rest:
                    continue
            headers.append(
                Header(
                    page=pi,
                    top=ln["top"],
                    left=ln["left"],
                    kind="question",
                    number=number,
                    points=points,
                    text=rest.strip(),
                )
            )
    headers.sort(key=lambda h: (h.page, h.top, h.left))
    for i, h in enumerate(headers):
        h.seq = i
    return headers


def header_for_group(group: dict[str, Any], headers: list[Header]) -> Header | None:
    first = group["a"]
    best: Header | None = None
    for h in headers:
        if h.page < first["page"]:
            best = h
        elif h.page == first["page"] and h.top <= first["cy"] + 1:
            if best is None or (best.page, best.top) < (h.page, h.top):
                best = h
            elif (best.page, best.top) == (h.page, h.top):
                # Misma línea: quedarse con la cabecera más a la izquierda.
                if h.left <= first["left"] and h.left > best.left:
                    best = h
    return best


def parse_penalty(first_page_text: str) -> dict[str, Any]:
    t = first_page_text.lower()
    t = re.sub(r"\s+", " ", t)
    if re.search(r"incorrectas?\s+no\s+restan|no\s+restan", t):
        return {"type": "none", "text": "Las respuestas incorrectas no restan."}
    m = re.search(
        r"cada\s+(\d+)\s+preguntas?\s+de\s+test\s+con\s+(\d+)\s+opciones?\s+o\s+menos.*?se\s+resta\s+(\d+(?:[.,]\d+)?)\s+punto",
        t,
    )
    if m:
        return {
            "type": "groups",
            "n": int(m.group(1)),
            "maxOptions": int(m.group(2)),
            "points": float(m.group(3).replace(",", ".")),
            "text": f"Cada {m.group(1)} fallos de preguntas con {m.group(2)} opciones o menos restan {m.group(3)} punto(s).",
        }
    m = re.search(
        r"cada\s+(\d+)\s+preguntas?.*?restan?\s+(\d+(?:[.,]\d+)?)\s+punto", t
    )
    if m:
        return {
            "type": "groups",
            "n": int(m.group(1)),
            "maxOptions": None,
            "points": float(m.group(2).replace(",", ".")),
            "text": f"Cada {m.group(1)} fallos restan {m.group(2)} punto(s).",
        }
    m = re.search(r"tres\s+preguntas?.*?restan?\s+(?:un|1)\s+punto", t)
    if m:
        return {
            "type": "groups",
            "n": 3,
            "maxOptions": None,
            "points": 1,
            "text": "Cada 3 fallos restan 1 punto.",
        }
    m = re.search(
        r"resta\s+1\s*/\s*(\d+)\s+de\s+la\s+nota\s+de\s+la\s+pregunta", t
    )
    if m:
        n = int(m.group(1))
        return {
            "type": "fraction",
            "fraction": 1.0 / n,
            "text": f"Cada fallo resta 1/{n} de la nota de la pregunta.",
        }
    m = re.search(
        r"cada\s+pregunta\s+incorrecta\s+resta\s+(\d+(?:[.,]\d+)?)\s+punto", t
    )
    if m:
        return {
            "type": "perWrong",
            "points": float(m.group(1).replace(",", ".")),
            "text": f"Cada fallo resta {m.group(1)} punto(s).",
        }
    m = re.search(r"(\d+(?:[.,]\d+)?)\s+puntos?\s+por\s+cada\s+fallo", t)
    if m:
        return {
            "type": "perWrong",
            "points": float(m.group(1).replace(",", ".")),
            "text": f"Cada fallo resta {m.group(1)} punto(s).",
        }
    return {"type": "none", "text": "Sin penalización indicada."}


def declared_total(first_page_text: str) -> float | None:
    t = re.sub(r"\s+", " ", first_page_text)
    m = re.search(r"total\s+de\s+(\d+(?:[.,]\d+)?)\s+puntos", t, re.I)
    if m:
        return float(m.group(1).replace(",", "."))
    m = re.search(r"suma\s+un\s+total\s+de\s+(\d+(?:[.,]\d+)?)\s+puntos", t, re.I)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


# ---------------------------------------------------------------------------
# Nombres y metadatos de archivos
# ---------------------------------------------------------------------------


CODE_LABELS = [
    (re.compile(r"^P(\d+)R$", re.I), lambda m: f"Prueba {m.group(1)} · Recuperación"),
    (re.compile(r"^P(\d+)X$", re.I), lambda m: f"Prueba {m.group(1)} · Extraordinaria"),
    (re.compile(r"^P(\d+)$", re.I), lambda m: f"Prueba {m.group(1)}"),
    (re.compile(r"^P(\d+)R_$", re.I), lambda m: f"Prueba {m.group(1)} · Recuperación"),
    (re.compile(r"^C(\d+)$", re.I), lambda m: f"Control {m.group(1)}"),
    (re.compile(r"^ordinario-test-(\d+)$", re.I), lambda m: f"Test ordinario ({m.group(1)} preguntas)"),
    (re.compile(r"^ordinario-test$", re.I), lambda m: "Test ordinario"),
    (re.compile(r"^ordinario-problemas$", re.I), lambda m: "Problemas ordinarios"),
    (re.compile(r"^ordinario-recuperacion$", re.I), lambda m: "Recuperación ordinaria"),
    (re.compile(r"^ordinario-teor[ií]a$", re.I), lambda m: "Teoría ordinaria"),
    (re.compile(r"^ordinario-lab$", re.I), lambda m: "Laboratorio ordinario"),
    (re.compile(r"^ordinario-final$", re.I), lambda m: "Examen final"),
    (re.compile(r"^extra-P(\d+)(X)?$", re.I), lambda m: f"Prueba {m.group(1)} extra"),
    (re.compile(r"^extra-teor[ií]a$", re.I), lambda m: "Teoría extra"),
    (re.compile(r"^extra-test$", re.I), lambda m: "Test extra"),
    (re.compile(r"^extra-lab$", re.I), lambda m: "Laboratorio extra"),
    (re.compile(r"^PTX$", re.I), lambda m: "Prueba de teoría · Extraordinaria"),
    (re.compile(r"^readingsX$", re.I), lambda m: "Lecturas · Extraordinaria"),
    (re.compile(r"^LabX$", re.I), lambda m: "Laboratorio · Extraordinaria"),
    (re.compile(r"^clickers$", re.I), lambda m: "Clickers"),
    (re.compile(r"^repaso$", re.I), lambda m: "Repaso"),
    (re.compile(r"^final$", re.I), lambda m: "Examen final"),
]


def code_label(code: str) -> str:
    for rx, fn in CODE_LABELS:
        m = rx.match(code)
        if m:
            return fn(m)
    text = code.replace("-", " ").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else "Examen"


def split_filename(filename: str) -> dict[str, Any]:
    stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
    solved = stem.lower().endswith(".solved")
    if solved:
        stem = stem[: -len(".solved")]
    subject = stem.split("_", 1)[0]
    rest = stem[len(subject) + 1 :] if stem.startswith(subject + "_") else stem
    lang = "es"
    m = re.search(r"_(en|es)$", rest, re.I)
    if m:
        lang = m.group(1).lower()
        rest = rest[: m.start()]
    year4 = rest[:4] if re.match(r"^\d{4}", rest) else ""
    code = rest[5:] if year4 and rest[4:5] == "_" else rest[4:] if year4 else rest
    code = code.strip("_")
    if year4:
        year = f"20{year4[:2]}/{year4[2:]}"
        year_sort = 2000 + int(year4[:2])
    else:
        year = ""
        year_sort = 0
    return {
        "stem": stem,
        "subject": subject,
        "year4": year4,
        "year": year,
        "yearSort": year_sort,
        "code": code,
        "codeLabel": code_label(code),
        "language": lang,
        "solved": solved,
    }


def slugify(text: str) -> str:
    text = text.lower()
    text = unicodedata_normalize(text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def unicodedata_normalize(text: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Texto completo de enunciados y opciones
# ---------------------------------------------------------------------------

MONO_FONT_RE = re.compile(r"mono|nimbusmon|typewriter|courier|cmtt|consol|menlo", re.I)
RUNNING_TEXT_RE = re.compile(r"^\d+(\s*/\s*\d+)?$|Escuela Superior de Inform|^Página\s+\d+", re.I)
OPTION_PREFIX_RE = re.compile(r"^\(?([A-Za-z])\s*[.\)]\s*")
MAX_STEM_CHARS = 2000
MAX_OPTION_CHARS = 600


SPACED_TEXT_RE = re.compile(r"(?:^|\s)\S\s\S\s\S(?:\s|$)")


def bbox_words(path: Path) -> list[list[dict[str, Any]]]:
    """Palabras de cada página con su posición, según pdftotext."""
    out = run(["pdftotext", "-bbox", str(path), "-"])
    pages: list[list[dict[str, Any]]] = []
    for pm in re.finditer(r"<page [^>]*>(.*?)</page>", out, re.S):
        words = []
        for wm in re.finditer(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>',
            pm.group(1),
            re.S,
        ):
            x0, y0, x1, _y1, text = wm.groups()
            words.append(
                {"x0": float(x0), "y0": float(y0), "x1": float(x1), "text": html.unescape(text)}
            )
        pages.append(words)
    return pages


def repair_spaced_items(pages: list[dict[str, Any]], words_by_page: list[list[dict[str, Any]]]) -> None:
    """pdftohtml separa las letras de los listados; pdftotext las une bien."""
    for pi, page in enumerate(pages):
        words = words_by_page[pi] if pi < len(words_by_page) else []
        for it in page["items"]:
            family = page["fonts"].get(it["font"], {}).get("family", "")
            if not it["text"] or not (MONO_FONT_RE.search(family) or SPACED_TEXT_RE.search(it["text"])):
                continue
            inside = sorted(
                (
                    w
                    for w in words
                    if abs(w["y0"] - it["top"]) < 3
                    and w["x0"] >= it["left"] - 1
                    and w["x1"] <= it["left"] + it["w"] + 1
                ),
                key=lambda w: w["x0"],
            )
            if inside:
                it["text"] = " ".join(w["text"] for w in inside)


def is_mono(line: dict[str, Any], page: dict[str, Any]) -> bool:
    """Línea de listado: predomina la fuente monoespaciada (no un término suelto)."""
    # Los listados numerados llevan el número de línea como primera caja.
    if len(line["items"]) > 1 and re.fullmatch(r"\d{1,3}", line["items"][0]["text"].strip()):
        return True
    total = sum(len(it["text"]) for it in line["items"])
    mono = sum(
        len(it["text"])
        for it in line["items"]
        if MONO_FONT_RE.search(page["fonts"].get(it["font"], {}).get("family", ""))
    )
    return total > 0 and mono / total >= 0.6


def join_lines(lines: list[dict[str, Any]]) -> str:
    """Une líneas de un PDF: repara guiones finales y respeta los listados de código."""
    text = ""
    previous_mono = False
    mono_left = min(
        (ln["left"] for ln in lines if ln.get("mono")), default=0.0
    )
    for ln in lines:
        piece = ln["text"].strip()
        if not piece:
            continue
        mono = bool(ln.get("mono"))
        if mono:
            first = ln["items"][0]
            char_w = first["w"] / max(1, len(first["text"])) or 5.0
            piece = " " * max(0, round((ln["left"] - mono_left) / char_w)) + piece
        if not text:
            text = piece
        elif mono or previous_mono:
            text += "\n" + piece
        elif re.search(r"\w-$", text) and piece[0].islower():
            text = text[:-1] + piece
        else:
            text += " " + piece
        previous_mono = mono
    return text.strip()


def option_full_text(
    m: dict[str, Any],
    page: dict[str, Any],
    page_markers_list: list[dict[str, Any]],
    page_headers: list[Header],
    consumed: set[int],
) -> str:
    """Texto completo de una opción, incluidas sus líneas de continuación."""
    limit_y = page["H"]
    for other in page_markers_list:
        if abs(other["left"] - m["left"]) < 6 and other["cy"] > m["cy"] + 3:
            limit_y = min(limit_y, other["top"])
    for h in page_headers:
        if h.top > m["cy"] + 3:
            limit_y = min(limit_y, h.top)
    col_right = page["W"]
    for other in page_markers_list:
        if other["left"] > m["left"] + 10 and m["cy"] - 5 <= other["cy"] < limit_y:
            col_right = min(col_right, other["left"])

    candidates = [
        it
        for it in page["items"]
        if it["text"]
        and it["left"] > m["left"] - 15
        and (it["left"] > m["left"] + 1 or it["top"] + it["h"] / 2 > m["cy"] + 5.5)
        and it["left"] < col_right - 1
        and m["cy"] - 5.5 <= it["top"] + it["h"] / 2 < limit_y
    ]
    lines = build_lines({"items": candidates})
    if not lines:
        return m.get("otext", "")
    for ln in lines:
        ln["mono"] = is_mono(ln, page)

    first = lines[0]
    if abs(first["cy"] - m["cy"]) > 5.5:
        return m.get("otext", "")
    kept = [first]
    text_left = first["left"]
    # La letra puede ir en su propia caja: la sangría real es la del texto.
    if len(first["items"]) > 1 and len(first["items"][0]["text"]) <= 2:
        text_left = first["items"][1]["left"]
    # Si bajo la letra no hay texto, la opción es un bloque (código, tabla) que
    # puede empezar más a la izquierda que la letra.
    letter_only = bool(re.fullmatch(r"\(?[A-Za-z]\s*[.\)]?", first["text"].strip()))
    min_left = m["left"] - 15 if letter_only else min(text_left, first["left"]) - 3
    for ln in lines[1:]:
        gap = ln["cy"] - kept[-1]["cy"]
        height = max(it["h"] for it in kept[-1]["items"])
        if gap > max(1.7 * height, 16) or ln["left"] < min_left:
            break
        kept.append(ln)

    for ln in kept:
        for it in ln["items"]:
            consumed.add(id(it))
    text = join_lines(kept)
    prefix = OPTION_PREFIX_RE.match(text)
    if not prefix or prefix.group(1).lower() != m["letter"]:
        return m.get("otext", "")
    rest = text[prefix.end():].strip()
    return "" if not rest.strip(" .") else rest


def stem_lines_between(
    pages: list[dict[str, Any]],
    start: tuple[int, float],
    end: tuple[int, float],
    consumed: set[int],
) -> list[dict[str, Any]]:
    """Líneas no usadas por opciones entre dos posiciones (página, y) del examen."""
    collected: list[dict[str, Any]] = []
    for pi in range(start[0], end[0] + 1):
        page = pages[pi]
        items = []
        for it in page["items"]:
            if not it["text"] or id(it) in consumed:
                continue
            top = it["top"]
            if pi == start[0] and top <= start[1]:
                continue
            if pi == end[0] and top >= end[1]:
                continue
            # Al cambiar de página se saltan cabeceras y pies.
            if start[0] != end[0] and (top < page["H"] * 0.07 or top > page["H"] * 0.93):
                continue
            items.append(it)
        for ln in build_lines({"items": items}):
            if RUNNING_TEXT_RE.search(ln["text"].strip()):
                continue
            ln["mono"] = is_mono(ln, page)
            collected.append(ln)
    return collected


BLOCK_LABEL_RE = re.compile(r"^(?://\s*)?\(?([A-Za-z])\)\.?(?:\s+(.*))?$")


def assign_block_options(
    g: dict[str, Any],
    start: tuple[int, float],
    pages: list[dict[str, Any]],
    consumed: set[int],
) -> None:
    """Opciones con forma de bloque (código, tablas) etiquetado sobre las casillas.

    Estos exámenes muestran "a) <bloque>  c) <bloque>" y debajo las casillas sin
    texto. Se reparten los bloques por su etiqueta y su columna.
    """
    markers = {k: m for k, m in g.items() if re.fullmatch(r"[a-z]", k)}
    empty = {k for k, m in markers.items() if not m.get("otext", "").strip(" .")}
    if not empty:
        return
    first = min(markers.values(), key=lambda m: (m["page"], m["top"]))
    page = pages[first["page"]]
    top_limit = start[1] if start[0] == first["page"] else 0.0
    region = [
        it
        for it in page["items"]
        if it["text"] and id(it) not in consumed and top_limit < it["top"] < first["top"] - 1
    ]
    labels: dict[str, dict[str, Any]] = {}
    for it in region:
        match = BLOCK_LABEL_RE.match(it["text"].strip())
        if match:
            labels[match.group(1).lower()] = it
    if not empty <= set(labels):
        return

    for letter in empty:
        label = labels[letter]
        right = page["W"]
        bottom = first["top"] - 1
        for other in labels.values():
            if other is label:
                continue
            if other["left"] > label["left"] + 40:
                right = min(right, other["left"] - 20)
            elif other["top"] > label["top"] + 4 and abs(other["left"] - label["left"]) <= 40:
                bottom = min(bottom, other["top"] - 1)
        block = [
            it
            for it in region
            if it is not label
            and label["top"] < it["top"] < bottom
            and label["left"] - 20 <= it["left"] < right
            and it not in labels.values()
        ]
        lines = [ln for ln in build_lines({"items": block}) if not ln["text"].isdigit()]
        for ln in lines:
            ln["mono"] = is_mono(ln, page)
        inline = BLOCK_LABEL_RE.match(label["text"].strip()).group(2) or ""
        body = "\n".join(p for p in (inline, join_lines(lines)) if p)
        markers[letter]["otext"] = re.sub(r"(\w)-\n([a-záéíóúñ])", r"\1\2", body)

    # Todo lo que hay desde la primera etiqueta son opciones, no enunciado.
    first_label_top = min(label["top"] for label in labels.values())
    for it in region:
        if it["top"] >= first_label_top - 2:
            consumed.add(id(it))


def attach_full_text(
    groups: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    headers: list[Header],
    all_markers: list[dict[str, Any]],
    words_by_page: list[list[dict[str, Any]]],
) -> None:
    """Completa g["questionText"] y m["otext"] con todas las líneas del PDF."""
    repair_spaced_items(pages, words_by_page)
    consumed: set[int] = set()
    markers_by_page: dict[int, list[dict[str, Any]]] = {}
    for marker in all_markers:
        markers_by_page.setdefault(marker["page"], []).append(marker)
    headers_by_page: dict[int, list[Header]] = {}
    for h in headers:
        headers_by_page.setdefault(h.page, []).append(h)

    for g in groups:
        for letter, m in g.items():
            if re.fullmatch(r"[a-z]", letter):
                m["otext"] = option_full_text(
                    m,
                    pages[m["page"]],
                    markers_by_page[m["page"]],
                    headers_by_page.get(m["page"], []),
                    consumed,
                )

    previous: dict[str, Any] | None = None
    intro_by_header: dict[int, str] = {}
    for g in groups:
        h = g["header"]
        if h is None:
            previous = g
            continue
        markers = [m for k, m in g.items() if re.fullmatch(r"[a-z]", k)]
        first = min(markers, key=lambda m: (m["page"], m["top"]))
        end = (first["page"], first["top"] - 1)
        # Posición para situar elementos junto a la pregunta en el PDF. Por
        # defecto, la primera casilla (subapartados sin cabecera propia).
        g["anchor"] = [first["page"], round(first["left"], 2), round(first["cy"], 2)]
        if h.seq in intro_by_header and previous is not None:
            # Subapartado: enunciado común más el texto propio tras el anterior.
            last = max(
                (m for k, m in previous.items() if re.fullmatch(r"[a-z]", k)),
                key=lambda m: (m["page"], m["top"]),
            )
            assign_block_options(g, (last["page"], last["top"] + 1), pages, consumed)
            own = join_lines(
                stem_lines_between(pages, (last["page"], last["top"] + 1), end, consumed)
            )
            g["questionText"] = "\n".join(p for p in (intro_by_header[h.seq], own) if p)
        else:
            assign_block_options(g, (h.page, h.top + 3), pages, consumed)
            # Una línea de datos ("0.000754 ...") puede pasar por cabecera.
            start_header = h
            while start_header.number == "0" and start_header.seq > 0:
                start_header = headers[start_header.seq - 1]
            g["anchor"] = [
                start_header.page,
                round(start_header.left, 2),
                round(start_header.top + 5, 2),
            ]
            header_line = {"text": start_header.text, "items": [], "left": start_header.left}
            lines = stem_lines_between(
                pages, (start_header.page, start_header.top + 3), end, consumed
            )
            g["questionText"] = join_lines([header_line] + lines)
            intro_by_header[h.seq] = g["questionText"]
        previous = g


# ---------------------------------------------------------------------------
# Análisis de un examen
# ---------------------------------------------------------------------------


def analyze_exam(path: Path, meta: dict[str, Any]) -> dict[str, Any]:
    pages = xml_pages(path)
    glyph_pages = bbox_marker_glyphs(path)

    all_markers: list[dict[str, Any]] = []
    for pi, page in enumerate(pages):
        glyphs = glyph_pages[pi] if pi < len(glyph_pages) else []
        for marker in page_markers(page, glyphs):
            opt = option_letter(marker, page["items"])
            if not opt:
                continue
            letter, text = opt
            if not re.fullmatch(r"[a-z]", letter):
                continue
            marker.update(
                {
                    "page": pi,
                    "letter": letter,
                    "otext": text,
                    "pageW": page["W"],
                    "pageH": page["H"],
                }
            )
            all_markers.append(marker)

    all_markers.sort(key=lambda m: (m["page"], round(m["cy"], 1), m["left"]))
    raw_groups: list[list[dict[str, Any]]] = []
    for marker in all_markers:
        if marker["letter"] == "a" or not raw_groups:
            raw_groups.append([])
        raw_groups[-1].append(marker)

    # Agrupar y quitar letras duplicadas (capas ocultas, etc.)
    groups: list[dict[str, Any]] = []
    for raw in raw_groups:
        by_letter: dict[str, dict[str, Any]] = {}
        for m in raw:
            by_letter.setdefault(m["letter"], m)
        if len(by_letter) >= 2:
            groups.append(by_letter)

    headers = extract_headers(pages)
    first_page_text = run(["pdftotext", "-f", "1", "-l", "1", "-layout", str(path), "-"])
    # Reunir palabras partidas al final de línea (p. ej. "pre-\ngunta").
    first_page_text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", first_page_text)
    first_page_text = re.sub(r"\s+", " ", first_page_text)

    # Asignar cabecera y puntos
    block_headers = [h for h in headers if h.kind == "block"]
    for g in groups:
        h = header_for_group(g, headers)
        g["header"] = h
        g["points"] = h.points if h and h.points else None
        g["number"] = h.number if h and h.kind == "question" else None
        g["questionText"] = h.text if h else ""

    # Distribuir puntos de bloques entre las preguntas que no los declaren.
    for bi, bh in enumerate(block_headers):
        next_block = block_headers[bi + 1] if bi + 1 < len(block_headers) else None
        in_block: list[dict[str, Any]] = []
        for g in groups:
            h = g["header"]
            if h is None:
                continue
            after = (h.page, h.top) >= (bh.page, bh.top)
            before = next_block is None or (h.page, h.top) < (next_block.page, next_block.top)
            if after and before:
                in_block.append(g)
        missing = [g for g in in_block if g["points"] is None]
        if missing and bh.points:
            for g in missing:
                g["points"] = bh.points / len(missing)
        for g in in_block:
            if g["points"] is None:
                g["points"] = 1.0

    # Varias preguntas pueden compartir la misma cabecera (subapartados de un
    # problema con opciones). Repartir los puntos del enunciado entre ellas.
    by_header: dict[int, list[dict[str, Any]]] = {}
    for g in groups:
        h = g["header"]
        if h is not None and h.kind == "question" and h.points:
            by_header.setdefault(h.seq, []).append(g)
    for seq, shared in by_header.items():
        if len(shared) <= 1:
            continue
        h = shared[0]["header"]
        share = float(h.points) / len(shared)
        for i, g in enumerate(shared):
            g["points"] = share
            g["sub"] = i + 1
            g["subCount"] = len(shared)

    for g in groups:
        if g["points"] is None:
            g["points"] = 1.0

    attach_full_text(groups, pages, headers, all_markers, bbox_words(path))

    # Construir preguntas corregibles
    questions: list[dict[str, Any]] = []
    for idx, g in enumerate(groups):
        letters = sorted(k for k in g if re.fullmatch(r"[a-z]", k))
        correct = sorted(k for k in letters if g[k]["filled"])
        if not correct:
            continue
        if len(letters) < 2:
            continue
        h = g["header"]
        qtext = g.get("questionText") or ""
        multi = len(correct) > 1 or bool(
            re.search(
                r"marca\s+(todas|todos)|selecciona\s+(todas|todas?|todos)|indica\s+(todas|todos)|"
                r"todas\s+las\s+(correctas|que)|todos\s+los\s+que|select\s+all|mark\s+all|choose\s+all|"
                r"which\s+of\s+the\s+following\s+are",
                qtext,
                re.I,
            )
        )
        qnum = g.get("number") or str(idx + 1)
        if g.get("sub"):
            qnum = f"{qnum}.{g['sub']}"
        options = []
        for letter in letters:
            m = g[letter]
            # Zona clicable: desde el cuadro hasta el siguiente cuadro de la
            # misma línea (o el margen derecho).
            max_right = m["pageW"] - 30
            for other in all_markers:
                if (
                    other["page"] == m["page"]
                    and other is not m
                    and abs(other["cy"] - m["cy"]) < 5
                    and other["left"] > m["left"] + 1
                ):
                    max_right = min(max_right, other["left"] - 2)
            zone_w = max(m["w"] + 4, max_right - m["left"])
            # Algunos cuadros quedan pegados al borde inferior; recortamos las
            # cajas para que no se salgan de la página.
            rect_x = round(max(0.0, m["left"] - 1), 2)
            rect_y = round(max(0.0, m["top"] - 1), 2)
            rect_w = round(min(m["w"] + 2, m["pageW"] - rect_x), 2)
            rect_h = round(min(m["h"] + 2, m["pageH"] - rect_y), 2)
            zone_x = round(max(0.0, m["left"] - 2), 2)
            zone_y = round(max(0.0, min(m["cy"] - 9, m["pageH"] - 18)), 2)
            zone_w = round(min(zone_w, m["pageW"] - zone_x), 2)
            zone_h = round(min(18, m["pageH"] - zone_y), 2)
            options.append(
                {
                    "letter": letter,
                    "page": m["page"],
                    "rect": [rect_x, rect_y, rect_w, rect_h],
                    "zone": [zone_x, zone_y, zone_w, zone_h],
                    "correct": letter in correct,
                    "text": m.get("otext", "")[:MAX_OPTION_CHARS],
                }
            )
        questions.append(
            {
                "id": f"q{len(questions) + 1}",
                "number": qnum,
                "points": round(float(g["points"]), 2),
                "multi": multi,
                "text": qtext[:MAX_STEM_CHARS],
                "anchor": g.get("anchor"),
                "answer": correct,
                "options": options,
            }
        )

    # ¿Hay solución? Si no hay ninguna pregunta con respuesta marcada, el PDF
    # se ofrece en modo lectura.
    interactive = bool(questions)
    max_score = round(sum(q["points"] for q in questions), 2) if questions else 0.0
    declared = declared_total(first_page_text)
    scale = None
    if questions and declared and max_score > declared * 1.05:
        # Algunos PDFs antiguos tienen erratas en los puntos por pregunta.
        # Si la suma supera el total declarado, normalizamos al total real.
        scale = declared / max_score
        for q in questions:
            q["points"] = round(q["points"] * scale, 2)
        max_score = round(sum(q["points"] for q in questions), 2)
        if questions and abs(max_score - declared) > 0.01:
            questions[-1]["points"] = round(
                questions[-1]["points"] + (declared - max_score), 2
            )
            max_score = declared

    return {
        "pages": len(pages),
        "pageWidth": pages[0]["W"] if pages else 595,
        "pageHeight": pages[0]["H"] if pages else 842,
        "pageSizes": [
            [round(p["W"], 2), round(p["H"], 2)] for p in pages
        ],
        "questions": questions,
        "interactive": interactive,
        "maxScore": max_score,
        "penalty": parse_penalty(first_page_text),
        "declaredTotal": declared,
        "scoreScale": scale,
        "markerCount": len(all_markers),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    if not SOURCE.exists():
        print(f"No existe {SOURCE}", file=sys.stderr)
        return 1
    OUT_PDFS.mkdir(parents=True, exist_ok=True)
    OUT_DATA.parent.mkdir(parents=True, exist_ok=True)
    new_pdf_names: set[str] = set()

    # 1. Reunir archivos de las tres asignaturas.
    found: list[Path] = []
    for f in sorted(SOURCE.iterdir()):
        if not f.is_file() or f.suffix.lower() != ".pdf":
            continue
        if f.name.split("_", 1)[0] not in SUBJECTS:
            continue
        found.append(f)

    # 2. Emparejar sin corregir / corregido. Para mostrar se usa siempre el
    #    PDF corregido (los cuadros de solución se tapan en la app).
    by_stem = {f.stem: f for f in found}
    entries: list[dict[str, Any]] = []
    for f in found:
        meta = split_filename(f.name)
        if meta["solved"]:
            continue
        solved = SOURCE / (f.stem + ".solved.pdf")
        if solved.exists():
            meta = split_filename(solved.name)
            meta["solved"] = True
            display = solved
        else:
            display = f
        meta["display"] = display
        entries.append(meta)

    # PDFs que solo existen en versión corregida.
    for f in found:
        meta = split_filename(f.name)
        if not meta["solved"]:
            continue
        base = f.name[: -len(".solved.pdf")]
        if (SOURCE / (base + ".pdf")).exists():
            continue
        meta["display"] = f
        entries.append(meta)

    # 3. Deduplicar por contenido (mismo examen con dos nombres).
    entries.sort(key=lambda m: (len(m["display"].name), m["display"].name))
    seen_hash: dict[str, dict[str, Any]] = {}
    unique: list[dict[str, Any]] = []
    for meta in entries:
        h = md5(meta["display"])
        if h in seen_hash:
            continue
        meta["md5"] = h
        seen_hash[h] = meta
        unique.append(meta)
    entries = unique

    # 4. Analizar y generar catálogo.
    catalog: list[dict[str, Any]] = []
    errors: list[str] = []
    used_slugs: set[str] = set()
    for i, meta in enumerate(entries, 1):
        display: Path = meta["display"]
        print(f"[{i}/{len(entries)}] {display.name}", flush=True)
        try:
            info = analyze_exam(display, meta)
        except Exception as exc:  # pragma: no cover - diagnóstico
            errors.append(f"{display.name}: {exc}")
            info = {
                "pages": 0,
                "pageWidth": 595,
                "pageHeight": 842,
                "questions": [],
                "interactive": False,
                "maxScore": 0,
                "penalty": {"type": "none", "text": ""},
                "declaredTotal": None,
                "markerCount": 0,
            }

        base_slug = slugify(meta["stem"])
        slug = base_slug
        n = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{n}"
            n += 1
        used_slugs.add(slug)
        pdf_name = slug + ".pdf"
        new_pdf_names.add(pdf_name)
        shutil.copy2(display, OUT_PDFS / pdf_name)

        exam_id = slug
        subject = meta["subject"]
        title = f"{SUBJECTS[subject]} · {meta['codeLabel']}"
        catalog.append(
            {
                "id": exam_id,
                "subject": subject,
                "subjectName": SUBJECTS[subject],
                "year": meta["year"],
                "yearSort": meta["yearSort"],
                "code": meta["code"],
                "codeLabel": meta["codeLabel"],
                "language": meta["language"],
                "title": title,
                "subtitle": f"Curso {meta['year']}" if meta["year"] else "Examen",
                "pdf": f"pdfs/{pdf_name}",
                "original": display.name,
                "solved": True,
                "interactive": info["interactive"],
                "pageCount": info["pages"],
                "pageWidth": info["pageWidth"],
                "pageHeight": info["pageHeight"],
                "pageSizes": info.get("pageSizes", []),
                "questionCount": len(info["questions"]),
                "maxScore": info["maxScore"],
                "declaredTotal": info["declaredTotal"],
                "scoreScale": info.get("scoreScale"),
                "penalty": info["penalty"],
                "questions": info["questions"],
            }
        )

    catalog.sort(
        key=lambda e: (
            SUBJECT_ORDER.get(e["subject"], 9),
            -e["yearSort"],
            e["codeLabel"].lower(),
            e["language"],
            e["id"],
        )
    )

    # Elimina PDFs antiguos solo cuando el catálogo nuevo ya está completo.
    for old_pdf in OUT_PDFS.glob("*.pdf"):
        if old_pdf.name not in new_pdf_names:
            old_pdf.unlink()

    payload = {
        "generatedAt": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "subjects": [
            {"id": k, "name": v} for k, v in SUBJECTS.items()
        ],
        "exams": catalog,
    }
    OUT_DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    interactive = [e for e in catalog if e["interactive"]]
    read_only = [e for e in catalog if not e["interactive"]]
    print()
    print(f"Exámenes: {len(catalog)} ({len(interactive)} corregibles, {len(read_only)} solo lectura)")
    print(f"Preguntas corregibles: {sum(e['questionCount'] for e in interactive)}")
    print(f"PDFs copiados: {len(list(OUT_PDFS.glob('*.pdf')))}")
    if errors:
        print("\nErrores:", file=sys.stderr)
        for e in errors:
            print("  -", e, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
