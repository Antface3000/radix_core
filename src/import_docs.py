"""Import DOCX and Markdown into a new or current chapter."""

from __future__ import annotations

import os
import zipfile
from xml.etree import ElementTree as ET

from src import chapters

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def markdown_to_text(md: str) -> str:
    return (md or "").replace("\r\n", "\n")


def docx_to_text(path: str) -> str:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    paras = []
    for p in root.iter(f"{_W}p"):
        texts = [t.text or "" for t in p.iter(f"{_W}t")]
        paras.append("".join(texts))
    return "\n".join(paras)


def import_file(chapters_dir: str, path: str, *, chapter_name: str | None = None) -> dict:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".md", ".markdown", ".txt"):
        with open(path, "r", encoding="utf-8") as fh:
            body = markdown_to_text(fh.read())
    elif ext == ".docx":
        body = docx_to_text(path)
    else:
        raise ValueError(f"Unsupported import type: {ext}")
    name = chapter_name or os.path.splitext(os.path.basename(path))[0]
    created = chapters.create(chapters_dir, name)
    chapters.write(chapters_dir, created["id"], body)
    created["content"] = body
    return created
