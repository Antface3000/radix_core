"""styles.csv sync - ported from unblocker/styles-csv.js.

Maintains a ComfyUI "Load Styles CSV" file so lore entries can drive per-subject
prompt blocks. Uses Python's csv module for parsing/serialization. The path is
configurable (settings services.styles_csv); if blank these helpers are no-ops.
"""

import csv
import io
import os

LORE_PREFIX = "Lore | "
DEFAULT_HEADERS = ["name", "prompt", "negative_prompt"]
APPEARANCE_MAX = 500


def lore_row_name(entry):
    name = str((entry or {}).get("name") or "Untitled").strip() or "Untitled"
    return f"{LORE_PREFIX}{name}"


def is_lore_row_name(name):
    return str(name or "").startswith(LORE_PREFIX)


def _wrap_bracket(raw):
    s = str(raw or "").strip()
    if not s:
        return ""
    if s.startswith("[") and s.endswith("]"):
        return s
    return f"[{s.strip('[]').strip()}]"


def _derive_appearance(entry):
    raw = (entry.get("appearance") or entry.get("description")
           or entry.get("notes") or "")
    return str(raw).strip()[:APPEARANCE_MAX]


def lore_entry_to_row(entry):
    display = str((entry or {}).get("name") or "Untitled").strip() or "Untitled"
    raw = str((entry or {}).get("imagePrompt") or "").strip()
    if raw:
        prompt = _wrap_bracket(raw)
    else:
        appearance = _derive_appearance(entry)
        inner = f"{display}, {appearance}" if appearance else display
        prompt = f"[{inner}]"
    return {
        "name": lore_row_name(entry),
        "prompt": prompt,
        "negative_prompt": str((entry or {}).get("imageNegativePrompt") or "").strip(),
    }


def join_bracket_blocks(parts):
    seen, blocks = set(), []
    for part in (parts or []):
        piece = str(part or "").strip()
        if not piece or piece.lower() in seen:
            continue
        seen.add(piece.lower())
        blocks.append(piece)
    return "\n".join(blocks)


def append_unique_csv_parts(base, additions):
    result = str(base or "").strip()
    for part in additions:
        piece = str(part or "").strip()
        if not piece:
            continue
        if not result:
            result = piece
            continue
        if piece.lower() in result.lower():
            continue
        result = f"{result}, {piece}"
    return result


def read_styles_csv(file_path):
    if not file_path or not os.path.exists(file_path):
        return {"headers": list(DEFAULT_HEADERS), "rows": [], "filePath": file_path}
    try:
        with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            records = [r for r in reader if any(str(c).strip() for c in r)]
    except OSError as exc:
        return {"headers": list(DEFAULT_HEADERS), "rows": [],
                "filePath": file_path, "error": str(exc)}
    if not records:
        return {"headers": list(DEFAULT_HEADERS), "rows": [], "filePath": file_path}

    first = records[0]
    if first and str(first[0]).strip().lower() == "name":
        headers = [str(h).strip() for h in first]
        data_records = records[1:]
    else:
        headers = list(DEFAULT_HEADERS)
        data_records = records
    rows = []
    for rec in data_records:
        row = {headers[c]: (rec[c] if c < len(rec) else "")
               for c in range(len(headers))}
        rows.append(row)
    return {"headers": headers, "rows": rows, "filePath": file_path}


def write_styles_csv(file_path, headers, rows):
    headers = headers or list(DEFAULT_HEADERS)
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(h, "") for h in headers])
    with open(file_path, "w", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())


def _upsert(rows, row, name_key="name"):
    for i, r in enumerate(rows):
        if str(r.get(name_key)) == str(row.get(name_key)):
            rows[i] = {**r, **row}
            return
    rows.append(dict(row))


def upsert_lore_row(file_path, entry):
    row = lore_entry_to_row(entry)
    data = read_styles_csv(file_path)
    _upsert(data["rows"], row)
    write_styles_csv(file_path, data["headers"], data["rows"])
    return row


def remove_lore_row(file_path, entry_or_name):
    if isinstance(entry_or_name, str):
        row_name = (entry_or_name if entry_or_name.startswith(LORE_PREFIX)
                    else f"{LORE_PREFIX}{entry_or_name}")
    else:
        row_name = lore_row_name(entry_or_name)
    data = read_styles_csv(file_path)
    kept = [r for r in data["rows"] if str(r.get("name")) != row_name]
    if len(kept) == len(data["rows"]):
        return False
    write_styles_csv(file_path, data["headers"], kept)
    return True


def find_row_by_entry_name(file_path, entry_name):
    row_name = f"{LORE_PREFIX}{str(entry_name or '').strip()}"
    for r in read_styles_csv(file_path)["rows"]:
        if str(r.get("name")) == row_name:
            return r
    return None


def reconcile_lore_rows(file_path, entries):
    """Sync the given lore entries into the CSV; returns count synced."""
    desired = [lore_entry_to_row(e) for e in (entries or [])]
    data = read_styles_csv(file_path)
    rows = data["rows"]
    for row in desired:
        _upsert(rows, row)
    write_styles_csv(file_path, data["headers"], rows)
    return {"synced": len(desired)}
