"""Rule-based lore auditing (offline, no LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src import lore, lore_types, chapters
from src import lore_capture_guard
from src.lore_migrate import infer_entry_type


@dataclass
class AuditIssue:
    severity: str  # error | warning | info
    code: str
    entry_id: str | None
    message: str
    fix_hint: str = ""
    fix_action: str | None = None  # auto-fix key when fixable
    fix_detail: str = ""


@dataclass
class ApplyFixReport:
    applied: int = 0
    skipped: int = 0
    details: list[str] = None

    def __post_init__(self):
        if self.details is None:
            self.details = []


def _type_specific_fields(entry_type: str) -> list[str]:
    keys = []
    for key, _, _ in lore_types.fields_for_entry_type(entry_type):
        if key not in ("keywords", "aliases", "tags", "notes"):
            keys.append(key)
    return keys


def _entry_text_blob(entry) -> str:
    parts = [
        entry.get("name") or "",
        entry.get("notes") or entry.get("content") or "",
    ]
    for key in _type_specific_fields(entry.get("entryType") or "character"):
        parts.append(str(entry.get(key) or ""))
    return " ".join(parts).lower()


def _manuscript_text(paths) -> str:
    if not paths:
        return ""
    chunks = []
    for ch in chapters.list_chapters(paths["chapters"]):
        data = chapters.read(paths["chapters"], ch["id"])
        chunks.append(data.get("content") or "")
    return "\n".join(chunks)


def audit_lore(paths, *, orphan_scan: bool = True) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    if not paths:
        return issues

    book = lore.read(paths["lore"])
    entries = book["characters"] + book["world"]
    manuscript_lower = ""
    manuscript_orig = ""
    if orphan_scan:
        manuscript_orig = _manuscript_text(paths)
        manuscript_lower = manuscript_orig.lower()

    names_seen: dict[str, list[str]] = {}
    keyword_map: dict[str, list[str]] = {}

    for entry in entries:
        eid = entry.get("id")
        name = (entry.get("name") or "").strip()
        et = entry.get("entryType") or (
            "character" if entry.get("type") == "character" else "place")
        bucket = entry.get("type")
        expected_bucket = lore_types.storage_for_entry_type(et)

        if bucket != expected_bucket:
            issues.append(AuditIssue(
                "warning", "bucket_mismatch", eid,
                f"{name}: entryType '{et}' belongs in '{expected_bucket}' bucket, not '{bucket}'.",
                "Re-save entry in the correct bucket.",
                fix_action="fix_bucket",
                fix_detail=f"Move to {expected_bucket} bucket.",
            ))

        if et in ("character", "place") and not entry.get("entryType"):
            issues.append(AuditIssue(
                "info", "legacy_type", eid,
                f"{name}: no explicit entryType (inferred as {et}).",
                "Upgrade legacy entries to persist typed canon.",
                fix_action="persist_type",
                fix_detail=f"Set entryType to '{et}'.",
            ))

        inferred = infer_entry_type(entry)
        if inferred != et and name and name.lower() != "untitled":
            issues.append(AuditIssue(
                "warning", "type_mismatch", eid,
                f"{name}: labeled [{et}] but content looks like [{inferred}].",
                f"Change entry type to {inferred} if correct.",
                fix_action="set_entry_type",
                fix_detail=f"Change entryType from '{et}' to '{inferred}'.",
            ))

        notes = (entry.get("notes") or entry.get("content") or "").strip()

        if not name or name.lower() in ("untitled", "new entry"):
            issues.append(AuditIssue(
                "warning", "bad_name", eid,
                f"Entry has placeholder name '{name or '(empty)'}'.",
                "Give the entry a proper name.",
                fix_action=None,
            ))

        if name and lore_capture_guard.is_meta_capture_text(
                f"{name}\n{notes}" if notes else name):
            issues.append(AuditIssue(
                "error", "capture_artifact", eid,
                f"{name}: looks like agent meta-talk, not story canon.",
                "Delete this entry — it was likely captured from model "
                "instructions about tags.",
                fix_action="delete_entry",
                fix_detail="Remove capture artifact.",
            ))

        typed_empty = all(
            not str(entry.get(k) or "").strip()
            for k in _type_specific_fields(et))
        if not notes and typed_empty:
            issues.append(AuditIssue(
                "warning", "thin_entry", eid,
                f"{name} [{et}]: no notes and no type-specific fields filled.",
                "Add notes or context fields in Story Bible → Lorebook.",
            ))

        kws = entry.get("keywords") or []
        aliases = entry.get("aliases") or []
        extra_kws = [
            k for k in kws
            if str(k).strip().lower() != name.lower()]
        if name and not extra_kws and not aliases:
            issues.append(AuditIssue(
                "info", "missing_keywords", eid,
                f"{name}: only default keyword — add aliases or extra keywords.",
                "Add keywords for better autoscan matching.",
                fix_action="add_keywords",
                fix_detail=f"Ensure '{name}' is in keywords.",
            ))

        if name:
            key = name.lower()
            names_seen.setdefault(key, []).append(eid or name)
        for kw in kws + aliases + ([name] if name else []):
            kwl = str(kw).strip().lower()
            if kwl:
                keyword_map.setdefault(kwl, []).append(eid or name)

        if orphan_scan and manuscript_lower and name:
            tokens = [name.lower()] + [str(k).lower() for k in kws + aliases]
            if not any(t and t in manuscript_lower for t in tokens):
                issues.append(AuditIssue(
                    "info", "manuscript_orphan", eid,
                    f"{name}: not mentioned in manuscript keywords/name scan.",
                    "Expected for unused canon; remove or reference in prose.",
                ))

    for key, ids in names_seen.items():
        if len(ids) > 1:
            issues.append(AuditIssue(
                "error", "duplicate_name", None,
                f"Duplicate name '{key}' on {len(ids)} entries.",
                "Rename or merge duplicates in Lorebook.",
            ))

    for kw, ids in keyword_map.items():
        unique_ids = list(dict.fromkeys(ids))
        if len(unique_ids) > 1 and len(kw) > 2:
            issues.append(AuditIssue(
                "warning", "duplicate_keyword", None,
                f"Keyword '{kw}' shared by {len(unique_ids)} entries (autoscan confusion).",
                "Use distinct keywords or aliases per entry.",
            ))

    if orphan_scan and manuscript_orig:
        for suggestion in _unmapped_proper_nouns(manuscript_orig, entries):
            issues.append(AuditIssue(
                "info", "unmapped_proper_noun", None,
                suggestion,
                "Consider adding a lore entry via Quick Add.",
            ))

    severity_order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: (severity_order.get(i.severity, 9), i.code))

    _attach_duplicate_fixes(issues, entries)
    return issues


def fixable_issues(issues: list[AuditIssue]) -> list[AuditIssue]:
    return [i for i in issues if i.fix_action]


def apply_fixes(paths, issues: list[AuditIssue]) -> ApplyFixReport:
    """Apply auto-fixes for selected audit issues."""
    report = ApplyFixReport()
    if not paths:
        return report

    book = lore.read(paths["lore"])
    all_entries = {
        e.get("id"): e for e in book["characters"] + book["world"] if e.get("id")}

    for issue in issues:
        if not issue.fix_action:
            report.skipped += 1
            continue
        eid = issue.entry_id
        if not eid:
            report.skipped += 1
            continue
        entry = all_entries.get(eid)
        if not entry:
            report.skipped += 1
            continue

        action = issue.fix_action
        name = entry.get("name") or "?"

        if action in ("set_entry_type", "persist_type", "fix_bucket"):
            if action == "set_entry_type":
                new_type = infer_entry_type(entry)
            else:
                new_type = (
                    entry.get("entryType")
                    or infer_entry_type(entry))
            patched = lore.normalize_entry({**entry, "entryType": new_type})
            lore.save_entry(paths["lore"], patched)
            all_entries[eid] = patched
            report.applied += 1
            report.details.append(f"{name}: {issue.fix_detail or action}")
        elif action == "add_keywords":
            kws = list(entry.get("keywords") or [])
            nm = entry.get("name") or ""
            if nm and nm not in kws:
                kws.insert(0, nm)
                patched = lore.normalize_entry({**entry, "keywords": kws})
                lore.save_entry(paths["lore"], patched)
                all_entries[eid] = patched
                report.applied += 1
                report.details.append(f"{name}: added keywords")
            else:
                report.skipped += 1
        elif action == "rename_duplicate":
            base_name = (entry.get("name") or "Untitled").strip()
            suffix = issue.fix_detail or " (copy)"
            new_name = base_name + suffix if suffix.startswith(" (") else f"{base_name} ({suffix})"
            patched = lore.normalize_entry({**entry, "name": new_name})
            lore.save_entry(paths["lore"], patched)
            all_entries[eid] = patched
            report.applied += 1
            report.details.append(f"Renamed to '{new_name}'")
        elif action == "dedupe_keyword":
            kw = issue.fix_detail
            if kw:
                kws = [k for k in (entry.get("keywords") or [])
                       if str(k).lower() != kw.lower()]
                aliases = [a for a in (entry.get("aliases") or [])
                           if str(a).lower() != kw.lower()]
                patched = lore.normalize_entry({
                    **entry, "keywords": kws, "aliases": aliases})
                lore.save_entry(paths["lore"], patched)
                all_entries[eid] = patched
                report.applied += 1
                report.details.append(f"{name}: removed keyword '{kw}'")
            else:
                report.skipped += 1
        elif action == "delete_entry":
            lore.remove(paths["lore"], eid)
            all_entries.pop(eid, None)
            report.applied += 1
            report.details.append(f"Deleted '{name}' (capture artifact)")
        else:
            report.skipped += 1

    return report


def _attach_duplicate_fixes(issues: list[AuditIssue], entries: list[dict]):
    """Add per-entry rename fixes for duplicate names (keep first, rename rest)."""
    by_name: dict[str, list[str]] = {}
    id_to_name = {e.get("id"): e.get("name") for e in entries}
    for entry in entries:
        key = (entry.get("name") or "").strip().lower()
        if key:
            by_name.setdefault(key, []).append(entry.get("id"))

    for key, ids in by_name.items():
        if len(ids) <= 1:
            continue
        for idx, eid in enumerate(ids[1:], start=2):
            issues.append(AuditIssue(
                "error", "duplicate_rename", eid,
                f"Rename duplicate '{id_to_name.get(eid, key)}' (copy {idx}).",
                "Auto-rename with a suffix to distinguish entries.",
                fix_action="rename_duplicate",
                fix_detail=f" (copy {idx})",
            ))

    # Keyword dedupe: for duplicate_keyword issues, offer remove from non-pinned
    kw_hits: dict[str, list[dict]] = {}
    for entry in entries:
        for kw in (entry.get("keywords") or []) + (entry.get("aliases") or []):
            kwl = str(kw).strip().lower()
            if len(kwl) > 2:
                kw_hits.setdefault(kwl, []).append(entry)

    for kw, ents in kw_hits.items():
        if len(ents) <= 1:
            continue
        ents_sorted = sorted(ents, key=lambda e: (
            e.get("pinned"), e.get("alwaysInclude"), e.get("name") or ""), reverse=True)
        for loser in ents_sorted[1:]:
            issues.append(AuditIssue(
                "warning", "dedupe_keyword_offer", loser.get("id"),
                f"{loser.get('name')}: drop shared keyword '{kw}' (conflicts with "
                f"{ents_sorted[0].get('name')}).",
                "Remove keyword from this entry to reduce autoscan confusion.",
                fix_action="dedupe_keyword",
                fix_detail=kw,
            ))


def _unmapped_proper_nouns(manuscript_lower: str, entries: list, limit: int = 8) -> list[str]:
    """Suggest capitalized tokens frequent in manuscript but absent from lore."""
    known = set()
    for e in entries:
        for token in (e.get("name") or "").split():
            known.add(token.lower())
        for kw in (e.get("keywords") or []) + (e.get("aliases") or []):
            known.add(str(kw).lower())

    counts: dict[str, int] = {}
    for match in re.finditer(r"\b([A-Z][a-z]{2,})\b", manuscript_lower.title()):
        word = match.group(1)
        wl = word.lower()
        if wl in known or wl in _STOP_WORDS:
            continue
        counts[wl] = counts.get(wl, 0) + 1

    ranked = sorted(counts.items(), key=lambda x: -x[1])
    out = []
    for word, count in ranked[:limit]:
        if count >= 3:
            out.append(
                f"Manuscript mentions '{word.title()}' {count}× with no lore entry.")
    return out


_STOP_WORDS = frozenset({
    "the", "and", "but", "for", "with", "from", "that", "this", "they",
    "she", "her", "his", "him", "was", "were", "had", "have", "not",
    "you", "your", "what", "when", "where", "who", "how", "all", "one",
    "said", "then", "there", "their", "would", "could", "should", "into",
    "chapter", "however", "though", "after", "before", "about", "just",
})


def preflight_checklist(paths, settings) -> list[tuple[str, bool, str]]:
    """Readiness rows for Focus Pre-Flight tab."""
    from src import story_bible, world_state, ambiguity

    rows: list[tuple[str, bool, str]] = []
    if not paths:
        rows.append(("Project loaded", False, "Open or create a project."))
        return rows

    bible = story_bible.read(paths["bible"])
    filled = sum(
        1 for k in ("premise", "logline", "genreTone", "synopsis", "worldRules")
        if str(bible.get(k) or "").strip())
    rows.append(("Story Bible fields", filled >= 2,
                 f"{filled}/5 core bible fields filled."))

    book = lore.read(paths["lore"])
    n_entries = len(book["characters"]) + len(book["world"])
    rows.append(("Lorebook entries", n_entries >= 1, f"{n_entries} entries."))

    ws = world_state.read(paths["world_state"])
    ws_ok = bool(ws.get("currentLocation") or ws.get("currentDate") or ws.get("scene"))
    rows.append(("World state set", ws_ok, "Location, date, or scene notes present."))

    chs = chapters.list_chapters(paths["chapters"])
    rows.append(("Chapters started", len(chs) >= 1, f"{len(chs)} chapter(s)."))

    thin, reason = ambiguity._canon_thin(paths)
    rows.append(("Setting context depth", not thin, reason or "SETTING block looks adequate."))

    issues = audit_lore(
        paths, orphan_scan=settings.get("lore.audit_orphan_scan", True))
    errors = sum(1 for i in issues if i.severity == "error")
    warnings = sum(1 for i in issues if i.severity == "warning")
    rows.append(("Canon audit clean", errors == 0 and warnings == 0,
                 f"{errors} errors, {warnings} warnings."))
    return rows
