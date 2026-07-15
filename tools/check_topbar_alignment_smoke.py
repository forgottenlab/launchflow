"""Verify clean top-bar background and vertical alignment at supported scales."""

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
    print("topbar alignment smoke ok")
    print("themes=dark,light")
    print("effective_scale=100%,125%,150%")
    return 0


def child_main(scale: str) -> int:
    import shutil
    import uuid

    temp = ROOT.parent / "test" / f"topbar-{os.getpid()}-{uuid.uuid4().hex}"
    temp.mkdir(parents=True)
    os.environ["LAUNCHFLOW_DATA_DIR"] = str(temp / "data 中文")
    sys.path.insert(0, str(ROOT))

    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from editor.ui.main_window import MainWindow
    from shared.app_logging import reset_app_logger_for_tests

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(f"scale={scale}: {message}")

    def distance(left: QColor, right: QColor) -> int:
        return sum(abs(a - b) for a, b in zip(left.getRgb()[:3], right.getRgb()[:3]))

    app = QApplication.instance() or QApplication([])
    window = MainWindow(ROOT)
    window.resize(1180, 760)
    window.show()
    app.processEvents()
    try:
        theme_samples: dict[str, QColor] = {}
        for theme_name, is_dark in (("dark", True), ("light", False)):
            window.is_dark_theme = is_dark
            window._apply_theme()
            app.processEvents()

            top_bar = window.top_bar
            require(top_bar.height() == 60, f"{theme_name} top bar height changed: {top_bar.height()}")
            center_y = top_bar.rect().center().y()
            controls = (
                window.plan_name_label,
                window.plan_name_edit,
                window.btn_save,
                window.btn_save_as,
                window.btn_trial_run,
                window.btn_export_exe,
            )
            for control in controls:
                local_center = control.mapTo(top_bar, control.rect().center()).y()
                require(abs(local_center - center_y) <= 2, f"{theme_name} {control.objectName() or type(control).__name__} is not vertically centered")

            pixmap = top_bar.grab()
            image = pixmap.toImage()
            ratio = pixmap.devicePixelRatio()
            samples = [
                image.pixelColor(QPoint(round(5 * ratio), round(y * ratio)))
                for y in (10, center_y, top_bar.height() - 10)
            ]
            require(max(distance(samples[0], color) for color in samples[1:]) <= 12, f"{theme_name} top bar has uneven background blocks")
            theme_samples[theme_name] = samples[0]

            if scale == "1.0":
                SCREENSHOTS.mkdir(parents=True, exist_ok=True)
                path = SCREENSHOTS / f"{theme_name}-topbar-aligned.png"
                require(pixmap.save(str(path), "PNG"), f"failed screenshot {path}")

        require(distance(theme_samples["dark"], theme_samples["light"]) >= 100, "theme backgrounds are not distinct")
        print(f"scale={scale}: background-and-alignment=ok")
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
