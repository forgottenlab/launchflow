"""
Smoke-test LaunchFlow's editor UI without requiring a real license.

The script creates a QApplication, instantiates MainWindow against a temporary
project root, finds the wait/delay QDoubleSpinBox widgets, and verifies that
their geometry and button behavior match the spinbox hitbox contract.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox

from editor.ui.main_window import MainWindow


def _check_spinbox_contract(window: MainWindow, spinbox: QDoubleSpinBox, name: str) -> None:
    if spinbox.minimum() != 0:
        raise AssertionError(f"{name}: unexpected minimum {spinbox.minimum()}")
    if spinbox.maximum() < 9999:
        raise AssertionError(f"{name}: maximum too small {spinbox.maximum()}")
    if spinbox.decimals() != 1:
        raise AssertionError(f"{name}: unexpected decimals {spinbox.decimals()}")
    if spinbox.singleStep() <= 0:
        raise AssertionError(f"{name}: singleStep must be positive")
    if spinbox.minimumWidth() < 150 or spinbox.height() < 36:
        raise AssertionError(f"{name}: spinbox too small for reliable clicking")

    stylesheet = window.styleSheet()
    required = [
        "QDoubleSpinBox::up-button",
        "QDoubleSpinBox::down-button",
        "subcontrol-position: top right",
        "subcontrol-position: bottom right",
    ]
    missing = [item for item in required if item not in stylesheet]
    if missing:
        raise AssertionError(f"{name}: missing QSS snippets {missing}")


def _click_spinbox_arrows(spinbox: QDoubleSpinBox) -> None:
    spinbox.setValue(1.0)
    spinbox.setFocus()
    QApplication.processEvents()

    up_pos = QPoint(spinbox.width() - 13, 8)
    down_pos = QPoint(spinbox.width() - 13, spinbox.height() - 8)

    before = spinbox.value()
    QTest.mouseClick(spinbox, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, up_pos)
    QApplication.processEvents()
    after_up = spinbox.value()
    if after_up <= before:
        raise AssertionError(f"up click did not increase value: before={before}, after={after_up}")

    QTest.mouseClick(spinbox, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, down_pos)
    QApplication.processEvents()
    after_down = spinbox.value()
    if after_down >= after_up:
        raise AssertionError(f"down click did not decrease value: before={after_up}, after={after_down}")


def main() -> None:
    app = QApplication.instance() or QApplication([])

    tmp_root = PROJECT_ROOT / ".gui-smoke-tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="launchflow-gui-smoke-",
        dir=tmp_root,
        ignore_cleanup_errors=True,
    ) as tmp_dir_str:
        window = MainWindow(Path(tmp_dir_str))
        window.show()
        QApplication.processEvents()

        spinboxes = {
            "app_delay_in": window.app_delay_in,
            "url_delay_in": window.url_delay_in,
            "cmd_delay_in": window.cmd_delay_in,
            "wait_seconds_in": window.wait_seconds_in,
        }

        discovered = window.findChildren(QDoubleSpinBox)
        if len(discovered) < len(spinboxes):
            raise AssertionError(f"expected at least {len(spinboxes)} spinboxes, found {len(discovered)}")

        for name, spinbox in spinboxes.items():
            _check_spinbox_contract(window, spinbox, name)

        _click_spinbox_arrows(window.wait_seconds_in)

        window.close()
        app.processEvents()

    print("editor gui smoke ok")
    print(f"spinbox_count={len(discovered)}")


if __name__ == "__main__":
    main()
