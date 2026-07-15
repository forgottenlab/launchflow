"""Render all editor field borders in both themes and three Qt scale factors."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = ROOT.parent / "test" / "v0.1.0-beta.1_2026-07-12_234445" / "screenshots"


def parent_main() -> int:
    for scale in ("1.0", "1.25", "1.5"):
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["QT_SCALE_FACTOR"] = scale
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--scale", scale],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
        )
        if result.returncode:
            raise SystemExit(f"scale {scale} failed:\n{result.stdout}\n{result.stderr}")
        print(result.stdout.strip())
    print("control border theme smoke ok")
    print("themes=dark,light")
    print("effective_scale=100%,125%,150%")
    print("fields=line-edit,text-edit,combo,spinbox; complete-frame")
    print("combo=left-separator,rounded-right,visible-arrow")
    print("spinbox=equal-buttons,left-separator,middle-separator,visible-arrows,hitbox")
    return 0


def child_main(scale: str) -> int:
    import shutil
    import uuid

    temp = ROOT.parent / "test" / f"control-border-{os.getpid()}-{uuid.uuid4().hex}"
    temp.mkdir(parents=True)
    os.environ["LAUNCHFLOW_DATA_DIR"] = str(temp / "data 中文")
    sys.path.insert(0, str(ROOT))

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionComboBox, QStyleOptionSpinBox

    from editor.ui.main_window import DARK_FIELD_TOKENS, LIGHT_FIELD_TOKENS, MainWindow
    from shared.app_logging import reset_app_logger_for_tests

    def distance(left: QColor, right: QColor) -> int:
        return sum(abs(a - b) for a, b in zip(left.getRgb()[:3], right.getRgb()[:3]))

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(f"scale={scale}: {message}")

    def is_line_color(color: QColor, tokens) -> bool:  # noqa: ANN001
        # Fractional Qt scale factors antialias a one-logical-pixel border into
        # two physical pixels. The blended pixel must still be substantially
        # closer to the line token than to the field background.
        line_distance = min(distance(color, QColor(tokens.field_border)), distance(color, QColor(tokens.field_border_focus)))
        return line_distance < 125

    def assert_outer_frame(widget, tokens, name: str) -> None:  # noqa: ANN001
        pixmap = widget.grab()
        image = pixmap.toImage()
        depth = max(2, round(pixmap.devicePixelRatio()) + 1)
        edge_samples = (
            [QPoint(image.width() // 2, offset) for offset in range(depth)],
            [QPoint(image.width() // 2, image.height() - 1 - offset) for offset in range(depth)],
            [QPoint(offset, image.height() // 2) for offset in range(depth)],
            [QPoint(image.width() - 1 - offset, image.height() // 4) for offset in range(depth)],
            [QPoint(image.width() - 1 - offset, image.height() * 3 // 4) for offset in range(depth)],
        )
        missing_groups = [samples for samples in edge_samples if not any(is_line_color(image.pixelColor(point), tokens) for point in samples)]
        missing = [
            (samples[0], [image.pixelColor(point).name() for point in samples])
            for samples in missing_groups
        ]
        require(not missing, f"{name} outer frame has gaps at {missing}")

    def assert_vertical_separator(widget, x: int, tokens, name: str) -> None:  # noqa: ANN001
        pixmap = widget.grab()
        image = pixmap.toImage()
        ratio = pixmap.devicePixelRatio()
        physical_x = round(x * ratio)
        matches = 0
        total = 0
        for sample_x in range(max(0, physical_x - 3), min(image.width(), physical_x + 4)):
            for y in range(round(4 * ratio), image.height() - round(4 * ratio)):
                total += 1
                matches += int(is_line_color(image.pixelColor(sample_x, y), tokens))
        require(matches >= max(4, total // 8), f"{name} left separator is missing")

    app = QApplication.instance() or QApplication([])
    window = MainWindow(ROOT)
    window.resize(1180, 760)
    window.show()
    app.processEvents()
    try:
        for theme_name, is_dark, tokens in (
            ("dark", True, DARK_FIELD_TOKENS),
            ("light", False, LIGHT_FIELD_TOKENS),
        ):
            window.is_dark_theme = is_dark
            window._apply_theme()
            window.editor_stack.setCurrentWidget(window.page_cmd)
            window.cmd_shell_in.clearFocus()
            app.processEvents()

            assert_outer_frame(window.plan_name_edit, tokens, f"{theme_name} LineEdit")
            assert_outer_frame(window.cmd_in, tokens, f"{theme_name} TextEdit")

            combo = window.cmd_shell_in
            combo_option = QStyleOptionComboBox()
            combo.initStyleOption(combo_option)
            combo_arrow = combo.style().subControlRect(
                QStyle.ComplexControl.CC_ComboBox,
                combo_option,
                QStyle.SubControl.SC_ComboBoxArrow,
                combo,
            )
            assert_outer_frame(combo, tokens, f"{theme_name} ComboBox")
            assert_vertical_separator(combo, combo_arrow.left(), tokens, f"{theme_name} ComboBox")
            combo_pixmap = combo.grab()
            combo_image = combo_pixmap.toImage()
            combo_ratio = combo_pixmap.devicePixelRatio()
            arrow_center = QPoint(round(combo_arrow.center().x() * combo_ratio), round(combo_arrow.center().y() * combo_ratio))
            arrow_color = combo_image.pixelColor(arrow_center)
            arrow_background = combo_image.pixelColor(
                QPoint(round((combo_arrow.left() + 4) * combo_ratio), arrow_center.y())
            )
            require(distance(arrow_color, arrow_background) >= 45, f"{theme_name} ComboBox arrow is not visible")

            window.editor_stack.setCurrentWidget(window.page_wait)
            spin = window.wait_seconds_in
            spin.clearFocus()
            app.processEvents()
            spin_option = QStyleOptionSpinBox()
            spin.initStyleOption(spin_option)
            up_rect = spin.style().subControlRect(
                QStyle.ComplexControl.CC_SpinBox,
                spin_option,
                QStyle.SubControl.SC_SpinBoxUp,
                spin,
            )
            down_rect = spin.style().subControlRect(
                QStyle.ComplexControl.CC_SpinBox,
                spin_option,
                QStyle.SubControl.SC_SpinBoxDown,
                spin,
            )
            require(
                up_rect.size() == down_rect.size(),
                f"{theme_name} SpinBox button dimensions differ; up={up_rect}, down={down_rect}",
            )
            assert_outer_frame(spin, tokens, f"{theme_name} SpinBox")
            assert_vertical_separator(spin, min(up_rect.left(), down_rect.left()), tokens, f"{theme_name} SpinBox")

            spin_pixmap = spin.grab()
            spin_image = spin_pixmap.toImage()
            spin_ratio = spin_pixmap.devicePixelRatio()
            boundary_rows = range(
                max(0, round((min(up_rect.bottom(), down_rect.top()) - 2) * spin_ratio)),
                min(spin_image.height(), round((max(up_rect.bottom(), down_rect.top()) + 3) * spin_ratio)),
            )
            middle_matches = max(
                sum(
                    is_line_color(spin_image.pixelColor(x, y), tokens)
                    for x in range(
                        round((up_rect.left() + 2) * spin_ratio),
                        max(round((up_rect.left() + 3) * spin_ratio), round((up_rect.right() - 1) * spin_ratio)),
                    )
                )
                for y in boundary_rows
            )
            if middle_matches == 0:
                sampled = {
                    y: sorted({
                        spin_image.pixelColor(x, y).name()
                        for x in range(round((up_rect.left() + 2) * spin_ratio), round((up_rect.right() - 1) * spin_ratio))
                    })
                    for y in boundary_rows
                }
                print(f"middle-debug theme={theme_name} up={up_rect} down={down_rect} rows={sampled}")
            require(
                middle_matches >= max(3, up_rect.width() // 3),
                f"{theme_name} SpinBox middle separator is missing; up={up_rect}, down={down_rect}, matches={middle_matches}",
            )

            for rect, direction in ((up_rect, "up"), (down_rect, "down")):
                center = QPoint(round(rect.center().x() * spin_ratio), round(rect.center().y() * spin_ratio))
                arrow = spin_image.pixelColor(center)
                background = spin_image.pixelColor(QPoint(round((rect.left() + 4) * spin_ratio), center.y()))
                require(distance(arrow, background) >= 45, f"{theme_name} SpinBox {direction} arrow is not visible")

            spin.setValue(2.0)
            before = spin.value()
            QTest.mouseClick(spin, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, up_rect.center())
            app.processEvents()
            after_up = spin.value()
            require(after_up > before, f"{theme_name} SpinBox up hitbox regressed")
            QTest.mouseClick(spin, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, down_rect.center())
            app.processEvents()
            require(spin.value() < after_up, f"{theme_name} SpinBox down hitbox regressed")

            if scale == "1.0":
                SCREENSHOTS.mkdir(parents=True, exist_ok=True)
                window.editor_stack.setCurrentWidget(window.page_cmd)
                app.processEvents()
                path = SCREENSHOTS / f"{theme_name}-combobox-spinbox-fixed.png"
                require(window.grab().save(str(path), "PNG"), f"failed to save screenshot {path}")

        print(f"scale={scale}: border-render-and-hitbox=ok")
        return 0
    finally:
        window.close()
        app.processEvents()
        reset_app_logger_for_tests()
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--scale":
        raise SystemExit(child_main(sys.argv[2]))
    raise SystemExit(parent_main())
