"""Exercise drag cleanup when Qt invalidates QListWidgetItem wrappers."""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = ROOT.parent / "test" / f"drag-lifecycle-{os.getpid()}-{uuid.uuid4().hex}"
TEMP.mkdir(parents=True)
os.environ["LAUNCHFLOW_DATA_DIR"] = str(TEMP / "data 中文")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtCore import QByteArray, QMimeData, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDragLeaveEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidgetItem  # noqa: E402

import editor.ui.main_window as main_window_module  # noqa: E402
from editor.ui.main_window import ReorderableStepList  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def add_item(widget: ReorderableStepList, step_id: str, name: str = "步骤") -> QListWidgetItem:
    item = QListWidgetItem(name)
    item.setData(Qt.ItemDataRole.UserRole, step_id)
    widget.addItem(item)
    return item


def main() -> int:
    app = QApplication.instance() or QApplication([])
    widget = ReorderableStepList(lambda: True, lambda source, target: target, lambda _offset: None)
    widget.resize(520, 240)
    widget.show()
    app.processEvents()

    original_drag = main_window_module.QDrag

    class DeletingDrag:
        """Controlled QDrag path that invalidates the old item during exec()."""

        def __init__(self, source: ReorderableStepList) -> None:
            self.source = source
            self.mime_data: QMimeData | None = None

        def setMimeData(self, mime_data: QMimeData) -> None:  # noqa: N802
            self.mime_data = mime_data

        def setPixmap(self, _pixmap) -> None:  # noqa: N802, ANN001
            pass

        def setHotSpot(self, _point) -> None:  # noqa: N802, ANN001
            pass

        def exec(self, _action):  # noqa: ANN001
            old = self.source.takeItem(0)
            step_id = old.data(Qt.ItemDataRole.UserRole)
            shiboken6.delete(old)
            replacement = add_item(self.source, step_id, "重建后的步骤")
            self.source.setCurrentItem(replacement)
            replacement.setSelected(True)
            return Qt.DropAction.MoveAction

    try:
        main_window_module.QDrag = DeletingDrag
        for index in range(20):
            widget.clear()
            step_id = f"step-{index}"
            item = add_item(widget, step_id, f"步骤 {index}")
            widget.setCurrentItem(item)
            item.setSelected(True)
            widget.startDrag(Qt.DropAction.MoveAction)
            require(widget.count() == 1, f"drag {index}: step count changed")
            require(widget.item(0).data(Qt.ItemDataRole.UserRole) == step_id, f"drag {index}: step id changed")
            require(widget.currentItem().data(Qt.ItemDataRole.UserRole) == step_id, f"drag {index}: selection not restored")
            require(not widget._drag_active, f"drag {index}: active state leaked")
            require(widget._dragging_step_id is None, f"drag {index}: step-id state leaked")
            require(widget._drop_target_index is None, f"drag {index}: drop target leaked")
            require(widget.item(0).foreground().style() == Qt.BrushStyle.NoBrush, f"drag {index}: gray foreground leaked")

        # Cancelled drag: exec returns without touching the model, and finally
        # must still clear every visual flag.
        class CancelDrag(DeletingDrag):
            def exec(self, _action):  # noqa: ANN001
                return Qt.DropAction.IgnoreAction

        main_window_module.QDrag = CancelDrag
        widget.clear()
        cancelled = add_item(widget, "cancelled")
        widget.setCurrentItem(cancelled)
        cancelled.setSelected(True)
        widget.startDrag(Qt.DropAction.MoveAction)
        require(not widget._drag_active and widget._dragging_step_id is None, "cancelled drag leaked state")

        # dragLeave has its own cleanup path and does not dereference a stale
        # item. Re-entry can recover the stable ID from MIME data.
        widget._drag_active = True
        widget._dragging_step_id = "cancelled"
        widget._drop_target_index = 0
        widget.dragLeaveEvent(QDragLeaveEvent())
        require(not widget._drag_active and widget._dragging_step_id is None, "dragLeave leaked state")

        # Controlled drop path: moving C to the top rebuilds the visible items,
        # preserves IDs/count, and ends with clean drag state.
        ids = ["A", "B", "C"]
        widget.clear()
        for step_id in ids:
            add_item(widget, step_id, step_id)
        widget.show()
        app.processEvents()

        def reorder(source: int, target: int) -> int:
            moved = ids.pop(source)
            ids.insert(target, moved)
            widget.clear()
            for current_id in ids:
                add_item(widget, current_id, current_id)
            widget.setCurrentRow(target)
            return target

        widget._reorder = reorder
        widget._drag_active = True
        widget._dragging_step_id = "C"
        mime = QMimeData()
        mime.setData(widget.DRAG_MIME_TYPE, QByteArray(b"C"))
        drop = QDropEvent(
            QPointF(10, 1),
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        widget.dropEvent(drop)
        require(ids == ["C", "A", "B"], f"drop produced wrong order: {ids}")
        require(widget.count() == 3, "drop changed step count")
        require([widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(3)] == ids, "drop changed IDs")
        require(widget.currentItem().data(Qt.ItemDataRole.UserRole) == "C", "drop selection was not restored")
        require(not widget._drag_active and widget._dragging_step_id is None, "drop leaked drag state")

        print("drag lifecycle smoke ok")
        print("repeated_drag=20")
        print("deleted_item_wrapper=no-post-exec-access")
        print("cancel,dragLeave,drop=clean")
        print("step_count,step_ids,selection=preserved")
        print("gray_state=none")
        return 0
    finally:
        main_window_module.QDrag = original_drag
        widget.close()
        app.processEvents()
        shutil.rmtree(TEMP, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
