"""Qt dialogs for pre-flight ambiguity checks."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from src.ambiguity import evaluate
from ui_qt.widgets.clarify_dialog import ask_clarifications


def run_ambiguity_gate(
    parent,
    app,
    prompt: str,
    *,
    interactive_questions: bool = True,
) -> tuple[bool, str]:
    """Return (proceed, possibly_enriched_prompt).

    Warnings always surface as toasts. Clarifying questions use a blocking
    Liaison dialog when ``interactive_questions`` is True (team jobs); on the
    Specialist tab pass False for toast-only hints.
    """
    paths = app.engine.paths
    settings = app.settings
    result = evaluate(paths, prompt, settings)

    if result.blocked and result.block_reason:
        box = QMessageBox(parent)
        box.setWindowTitle("Setting not configured")
        box.setText(result.block_reason)
        box.setInformativeText("Open Story Bible to add canon, or proceed anyway.")
        open_btn = box.addButton("Open Story Bible", QMessageBox.AcceptRole)
        proceed_btn = box.addButton("Proceed anyway", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == open_btn:
            app.show_feature("Story Bible")
            return False, prompt
        if clicked != proceed_btn:
            return False, prompt

    for warning in result.warnings:
        app.show_toast(warning)

    enriched = prompt
    if result.questions:
        if not interactive_questions:
            for q in result.questions[:3]:
                app.show_toast(f"Consider: {q}")
            return True, prompt

        proceed, answers = ask_clarifications(
            parent, result.questions[:3],
            preamble="Your request could go a few ways.")
        if not proceed:
            return False, prompt
        if answers:
            enriched = prompt + "\n\nAuthor clarifications:\n" + "\n".join(
                f"- {q} {a}" if q else f"- {a}" for q, a in answers)

    return True, enriched
