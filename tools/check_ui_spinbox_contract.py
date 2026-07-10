"""
Static UI contract check for LaunchFlow spinbox hit areas.

This intentionally avoids importing PySide6 so it can run in lightweight
validation environments. It verifies that QDoubleSpinBox keeps explicit
up/down subcontrol geometry instead of inheriting generic text-input padding.
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAIN_WINDOW = PROJECT_ROOT / "editor" / "ui" / "main_window.py"


def main() -> None:
    source = MAIN_WINDOW.read_text(encoding="utf-8")
    required_snippets = [
        "QDoubleSpinBox::up-button",
        "QDoubleSpinBox::down-button",
        "subcontrol-position: top right",
        "subcontrol-position: bottom right",
        "def _configure_seconds_spinbox",
        "setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)",
    ]

    missing = [snippet for snippet in required_snippets if snippet not in source]
    if missing:
        raise SystemExit("Missing spinbox contract snippets: " + ", ".join(missing))

    generic_rule = "QLineEdit, QTextEdit, QComboBox, QDoubleSpinBox {\n        border: 1px solid;\n        border-radius: 8px;\n        padding: 7px 10px;"
    if generic_rule in source:
        raise SystemExit("QDoubleSpinBox still inherits generic text-input padding")

    print("spinbox contract ok")


if __name__ == "__main__":
    main()
