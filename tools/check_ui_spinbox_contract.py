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
        "class ThemedDoubleSpinBox(QDoubleSpinBox)",
        "SC_SpinBoxUp",
        "SC_SpinBoxDown",
        "painter.drawPolygon(QPolygonF(points))",
        "class ThemedComboBox(QComboBox)",
        "QComboBox::drop-down",
        "SC_ComboBoxArrow",
        "class FieldThemeTokens",
        "def _field_control_qss",
        "border-left: 1px solid {tokens.separator}",
        "border-top: 1px solid {tokens.separator}",
        "border-top-right-radius: 7px",
        "border-bottom-right-radius: 7px",
        "subcontrol-origin: padding",
        "spinbox.setFixedHeight(40)",
    ]

    missing = [snippet for snippet in required_snippets if snippet not in source]
    if missing:
        raise SystemExit("Missing spinbox contract snippets: " + ", ".join(missing))

    generic_rule = "QLineEdit, QTextEdit, QComboBox, QDoubleSpinBox {\n        border: 1px solid;\n        border-radius: 8px;\n        padding: 7px 10px;"
    if generic_rule in source:
        raise SystemExit("QDoubleSpinBox still inherits generic text-input padding")

    transparent_arrow_rules = [
        "QDoubleSpinBox::up-arrow { opacity: 0",
        "QDoubleSpinBox::down-arrow { opacity: 0",
        "QDoubleSpinBox::up-arrow { color: transparent",
        "QDoubleSpinBox::down-arrow { color: transparent",
    ]
    if any(rule in source for rule in transparent_arrow_rules):
        raise SystemExit("Spinbox arrow style makes arrows transparent")

    print("spinbox contract ok")


if __name__ == "__main__":
    main()
