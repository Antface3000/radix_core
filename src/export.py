"""Export manuscript chapters and Story Bible canon to readable files."""

from __future__ import annotations

from src import chapters, lore, outline, story_bible, world_state, projects


def _fmt_ext(fmt: str) -> str:
    return "md" if fmt == "md" else "txt"


def export_chapter(paths, chapter_id: str, fmt: str = "txt") -> str:
    """Return one chapter as plain text or markdown."""
    data = chapters.read(paths["chapters"], chapter_id)
    name = data["name"]
    body = data["content"] or ""
    if fmt == "md":
        return f"# {name}\n\n{body}".rstrip() + "\n"
    return body.rstrip() + "\n"


def compile_manuscript(paths, fmt: str = "txt") -> str:
    """Concatenate all chapters in order."""
    parts = []
    for ch in chapters.list_chapters(paths["chapters"]):
        data = chapters.read(paths["chapters"], ch["id"])
        if fmt == "md":
            parts.append(f"# {data['name']}\n\n{(data['content'] or '').strip()}")
        else:
            parts.append(f"{data['name']}\n{'=' * len(data['name'])}\n\n"
                         f"{(data['content'] or '').strip()}")
    sep = "\n\n---\n\n" if fmt == "md" else "\n\n\n"
    return (sep.join(parts).rstrip() + "\n") if parts else ""


def export_bible_bundle(paths, project_id: str | None = None, fmt: str = "md") -> str:
    """Human-readable Story Bible + lore + world state + outline."""
    bible = story_bible.read(paths["bible"])
    ws = world_state.read(paths["world_state"])
    ol = outline.read_all(paths["outlines"])

    proj_name = project_id or "project"
    try:
        for p in projects.list_projects():
            if p["id"] == project_id:
                proj_name = p["name"]
                break
    except Exception:
        pass

    lines = [f"# Story Bible — {proj_name}", ""]

    field_labels = [
        ("premise", "Premise"),
        ("logline", "Logline"),
        ("genreTone", "Genre & Tone"),
        ("themes", "Themes"),
        ("worldRules", "World Rules"),
        ("styleNotes", "Style Notes"),
        ("pointOfView", "Point of View"),
        ("tense", "Tense"),
        ("synopsis", "Synopsis"),
    ]
    for key, label in field_labels:
        val = bible.get(key, "")
        if isinstance(val, list):
            val = ", ".join(str(v) for v in val if v)
        val = str(val or "").strip()
        if val:
            lines.extend([f"## {label}", "", val, ""])

    lore_entries = lore.all_entries(paths["lore"])
    if lore_entries:
        lines.extend(["## Lorebook", ""])
    from src import lore_types

    for entry in lore_entries:
        et = entry.get("entryType") or "character"
        kind = lore_types.ENTRY_TYPE_LABELS.get(et, et.title())
        name = entry.get("name", "Untitled")
        lines.append(f"### {name} ({kind})")
        for key, label, _multi in lore_types.fields_for_entry_type(et):
            val = entry.get(key)
            if key in ("keywords", "aliases", "tags") and val:
                val = ", ".join(str(v) for v in val if v)
            elif key == "relationships" and val:
                val = lore_types.format_relationships(val)
            else:
                val = str(val or "").strip()
            if val:
                lines.append(f"**{label}:** {val}")
        flags = []
        if entry.get("pinned"):
            flags.append("pinned")
        if entry.get("alwaysInclude"):
            flags.append("always include")
        if flags:
            lines.append(f"*({', '.join(flags)})*")
        lines.append("")

    ws_lines = []
    if ws.get("currentDate"):
        ws_lines.append(f"- **Date:** {ws['currentDate']}")
    if ws.get("currentLocation"):
        ws_lines.append(f"- **Location:** {ws['currentLocation']}")
    if (ws.get("scene") or "").strip():
        ws_lines.append(f"- **Scene:** {ws['scene'].strip()}")
    for label, key in (("Timeline", "timeline"), ("Factions", "factions"),
                       ("Ongoing events", "ongoingEvents"), ("Facts", "facts")):
        items = ws.get(key) or []
        if items:
            ws_lines.append(f"- **{label}:**")
            for item in items:
                ws_lines.append(f"  - {item}")
    if ws_lines:
        lines.extend(["## World State", ""] + ws_lines + [""])

    global_ol = ol.get("global") or {}
    if (global_ol.get("summary") or "").strip() or global_ol.get("beats"):
        lines.extend(["## Global Outline", ""])
        if global_ol.get("summary"):
            lines.append(global_ol["summary"].strip())
            lines.append("")
        for i, beat in enumerate(global_ol.get("beats") or [], 1):
            lines.append(f"{i}. {beat}")
        lines.append("")

    ch_outlines = ol.get("chapters") or {}
    if ch_outlines:
        lines.extend(["## Chapter Outlines", ""])
        ch_names = {c["id"]: c["name"] for c in chapters.list_chapters(paths["chapters"])}
        for cid, co in ch_outlines.items():
            title = ch_names.get(cid, cid[:8])
            summary = (co.get("summary") or "").strip()
            beats = co.get("beats") or []
            if not summary and not beats:
                continue
            lines.append(f"### {title}")
            if summary:
                lines.append(summary)
            for i, beat in enumerate(beats, 1):
                lines.append(f"{i}. {beat}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def compile_standard_manuscript(paths, author: str = "", title: str = "") -> str:
    """Courier-style plain manuscript: title page + chapter page breaks."""
    if not title:
        title = "Untitled"
    pages = [title.upper(), "", f"by {author}" if author else "", "", ""]
    for i, ch in enumerate(chapters.list_chapters(paths["chapters"])):
        data = chapters.read(paths["chapters"], ch["id"])
        if i:
            pages.append("\n\n# # #\n\n")
        pages.append(data["name"].upper())
        pages.append("")
        pages.append((data.get("content") or "").strip())
    return "\n".join(pages).rstrip() + "\n"


def _docx_document_xml(paragraphs: list[str]) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    parts = [
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<w:document xmlns:w="{ns}"><w:body>',
    ]
    for para in paragraphs:
        escaped = (para.replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;"))
        parts.append(
            f'<w:p><w:r><w:t xml:space="preserve">{escaped}</w:t></w:r></w:p>')
    parts.append("</w:body></w:document>")
    return "".join(parts).encode("utf-8")


def compile_docx_bytes(paths, title: str = "Manuscript") -> bytes:
    import io
    import zipfile
    text = compile_standard_manuscript(paths, title=title)
    paragraphs = text.split("\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                    '<Default Extension="xml" ContentType="application/xml"/>'
                    '<Override PartName="/word/document.xml" '
                    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                    '</Types>')
        zf.writestr("_rels/.rels",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                    '</Relationships>')
        zf.writestr("word/document.xml", _docx_document_xml(paragraphs))
    return buf.getvalue()


def compile_epub_bytes(paths, title: str = "Manuscript", author: str = "Author") -> bytes:
    import io
    import uuid
    import zipfile
    html_chapters = []
    for ch in chapters.list_chapters(paths["chapters"]):
        data = chapters.read(paths["chapters"], ch["id"])
        body = (data.get("content") or "").replace("&", "&amp;").replace("<", "&lt;")
        body = body.replace("\n", "<br/>\n")
        html_chapters.append((ch["id"], data["name"], body))
    uid = str(uuid.uuid4())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml",
                    '<?xml version="1.0"?><container version="1.0" '
                    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                    'media-type="application/oebps-package+xml"/></rootfiles></container>')
        manifests = []
        spines = []
        nav = ['<html xmlns="http://www.w3.org/1999/xhtml"><body><nav><ol>']
        for i, (cid, name, body) in enumerate(html_chapters, 1):
            href = f"ch{i}.xhtml"
            manifests.append(
                f'<item id="ch{i}" href="{href}" media-type="application/xhtml+xml"/>')
            spines.append(f'<itemref idref="ch{i}"/>')
            nav.append(f'<li><a href="{href}">{name}</a></li>')
            zf.writestr(f"OEBPS/{href}",
                        '<?xml version="1.0" encoding="utf-8"?>'
                        '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                        f'<title>{name}</title></head><body><h1>{name}</h1>'
                        f"<p>{body}</p></body></html>")
        nav.append("</ol></nav></body></html>")
        zf.writestr("OEBPS/nav.xhtml", "".join(nav))
        zf.writestr("OEBPS/content.opf",
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="3.0">'
                    f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                    f'<dc:identifier id="BookId">{uid}</dc:identifier>'
                    f'<dc:title>{title}</dc:title><dc:creator>{author}</dc:creator>'
                    '<dc:language>en</dc:language></metadata>'
                    f'<manifest>{"".join(manifests)}'
                    '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
                    f'</manifest><spine>{"".join(spines)}</spine></package>')
    return buf.getvalue()


def export_production_bible(paths, project_name: str = "Project") -> str:
    """Plain tables of people, places, factions, creatures for collaborators."""
    from src import lore_types
    book = lore.read(paths["lore"])
    lines = [f"# Production bible — {project_name}", ""]
    buckets = {
        "People": [],
        "Creatures": [],
        "Places": [],
        "Factions": [],
        "Other": [],
    }
    for entry in (book.get("characters") or []) + (book.get("world") or []):
        et = entry.get("entryType") or "concept"
        name = entry.get("name") or "Untitled"
        notes = (entry.get("notes") or "")[:240]
        row = f"| {name} | {et} | {notes.replace('|', '/')} |"
        if et in ("character",):
            buckets["People"].append(row)
        elif et == "creature":
            buckets["Creatures"].append(row)
        elif et == "place":
            buckets["Places"].append(row)
        elif et == "faction":
            buckets["Factions"].append(row)
        else:
            buckets["Other"].append(row)
    for heading, rows in buckets.items():
        if not rows:
            continue
        lines.extend([f"## {heading}", "", "| Name | Type | Notes |", "|---|---|---|"] + rows + [""])
    ws = world_state.read(paths["world_state"])
    loc = ws.get("currentLocation") or ""
    date = ws.get("currentDate") or ""
    if loc or date:
        lines.extend(["## World state", "", f"- Date: {date}", f"- Location: {loc}", ""])
    return "\n".join(lines).rstrip() + "\n"
