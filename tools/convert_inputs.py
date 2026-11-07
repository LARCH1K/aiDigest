"""Конвертирует .docx и .pptx из «Вводные данные/» в Markdown (папка «Вводные данные/md/»).

Только стандартная библиотека. Запуск: python tools/convert_inputs.py
Старые .doc не поддерживаются — их нужно пересохранить в .docx или оформить вручную.
"""
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "Вводные данные"
OUT = SRC / "md"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def md_table(rows):
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    # Пустые столбцы (артефакт исходных таблиц) убираем
    keep = [i for i in range(width) if any(r[i] for r in rows)]
    rows = [[r[i].replace("|", "\\|") for i in keep] for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(keep)]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


# ---------- DOCX ----------

def docx_par(p):
    return clean("".join(t.text or "" for t in p.iter(W + "t")))


def docx_par_md(p):
    text = docx_par(p)
    if not text:
        return ""
    style = p.find(f"{W}pPr/{W}pStyle")
    style = style.get(W + "val", "") if style is not None else ""
    m = re.match(r"(?i)heading(\d)|заголовок(\d)", style)
    if m:
        return "#" * (int(m.group(1) or m.group(2)) + 1) + " " + text
    if p.find(f"{W}pPr/{W}numPr") is not None:
        return "- " + text
    return text


def docx_to_md(path):
    body = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml")).find(W + "body")
    blocks = []
    for el in body:
        if el.tag == W + "p":
            blocks.append(docx_par_md(el))
        elif el.tag == W + "tbl":
            rows = [[" ".join(filter(None, (docx_par(p) for p in tc.iter(W + "p"))))
                     for tc in tr.findall(W + "tc")]
                    for tr in el.findall(W + "tr")]
            blocks.append(md_table(rows))
    return "\n\n".join(b for b in blocks if b)


# ---------- PPTX ----------

def pptx_par(p):
    return clean("".join(t.text or "" for t in p.iter(A + "t")))


def pptx_shape(el, out):
    tag = el.tag
    if tag == P + "sp":
        for p in el.iter(A + "p"):
            if pptx_par(p):
                out.append(pptx_par(p))
    elif tag == P + "graphicFrame":
        tbl = next(el.iter(A + "tbl"), None)
        if tbl is not None:
            rows = [[" ".join(filter(None, (pptx_par(p) for p in tc.iter(A + "p"))))
                     for tc in tr.findall(A + "tc")]
                    for tr in tbl.findall(A + "tr")]
            out.append(md_table(rows))
    elif tag == P + "grpSp":
        for child in el:
            pptx_shape(child, out)


def pptx_to_md(path):
    z = zipfile.ZipFile(path)
    slides = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                    key=lambda n: int(re.search(r"\d+", n).group()))
    parts = []
    for i, name in enumerate(slides, 1):
        tree = ET.fromstring(z.read(name)).find(f"{P}cSld/{P}spTree")
        out = []
        for el in tree:
            pptx_shape(el, out)
        parts.append(f"## Слайд {i}\n\n" + "\n\n".join(out))
    return "\n\n".join(parts)


def main():
    OUT.mkdir(exist_ok=True)
    for path in sorted(SRC.iterdir()):
        ext = path.suffix.lower()
        if ext not in (".docx", ".pptx") or path.name.startswith("~$"):
            continue
        body = docx_to_md(path) if ext == ".docx" else pptx_to_md(path)
        target = OUT / (path.stem.strip() + ".md")
        target.write_text(f"<!-- Сконвертировано из «{path.name}» скриптом tools/convert_inputs.py -->\n\n"
                          f"# {path.stem.strip()}\n\n{body}\n", encoding="utf-8")
        print("ok:", target.relative_to(ROOT))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
