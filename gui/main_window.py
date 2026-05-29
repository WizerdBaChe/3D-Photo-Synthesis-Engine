"""
PySide6 主視窗 (Main Window View)
====================================
設計依據：DD-009（GUI 與引擎徹底解耦）、DD-010（PySide6 框架）、Red Line 1/3

規範：
  - 此檔案禁止 import 任何 src.core.* 或 src.app.orchestrator 模組。
  - View 層只觸發 Signal，不包含任何業務邏輯（View is Dumb）。
  - 耗時運算一律交由 SynthesisWorker (QThread) 執行（Red Line 1）。
  - 與渲染進程的通訊只透過 InputAdapter 與 RenderProcessController。
"""

from __future__ import annotations
import queue
import sys

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from src.app.adapter import InputAdapter
from src.app.render_ipc import RenderProcessController
from gui.worker import SynthesisWorker


class MainWindowView(QMainWindow):
    """
    3D Photo Synthesis Engine 主視窗（PSM Phase 6.4）。

    架構層次：
      View（此類）
        → InputAdapter（翻譯 Signal → DTO）
          → command_queue → SynthesisWorker（QThread）
                                → Orchestrator → RenderProcessController
          → pose_queue    → RenderProcessController（相機位姿 IPC）
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("3D Photo Synthesis Engine — MVP v1.0")
        self.setMinimumSize(640, 480)

        # 跨模組通訊佇列（DD-003）
        self._command_queue: queue.Queue = queue.Queue()
        self._pose_queue:    queue.Queue = queue.Queue()

        # 渲染進程控制器（子進程）
        self._render_ctrl = RenderProcessController()

        # 輸入適配器（GUI 事件 → DTO → Queue）
        self._adapter = InputAdapter(
            command_queue=self._command_queue,
            pose_queue=self._pose_queue,
        )

        # 背景 AI 運算執行緒
        self._worker = SynthesisWorker(
            command_queue=self._command_queue,
            render_controller=self._render_ctrl,
        )
        self._worker.progress_updated.connect(self._on_progress_updated)
        self._worker.synthesis_finished.connect(self._on_synthesis_finished)
        self._worker.synthesis_failed.connect(self._on_synthesis_failed)

        # 檔案路徑暫存（僅 View 層暫存，不傳入引擎）
        self._rgb_path:   str = ""
        self._depth_path: str = ""

        self._setup_ui()
        self._set_controls_enabled(False)

    # ------------------------------------------------------------------
    # UI 建構（View is Dumb：只有 Widget + Signal 連接）
    # ------------------------------------------------------------------

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setSpacing(12)
        root_layout.setContentsMargins(16, 16, 16, 16)

        root_layout.addWidget(self._build_file_group())
        root_layout.addWidget(self._build_rotation_group())
        root_layout.addWidget(self._build_action_group())
        root_layout.addWidget(self._build_status_group())

    def _build_file_group(self) -> QGroupBox:
        group = QGroupBox("輸入檔案")
        layout = QVBoxLayout(group)

        # RGB 圖片行
        rgb_row = QHBoxLayout()
        self._lbl_rgb = QLabel("RGB 圖片：未選擇")
        self._lbl_rgb.setWordWrap(True)
        btn_rgb = QPushButton("瀏覽…")
        btn_rgb.setFixedWidth(80)
        btn_rgb.clicked.connect(self._on_browse_rgb)
        rgb_row.addWidget(self._lbl_rgb, 1)
        rgb_row.addWidget(btn_rgb)
        layout.addLayout(rgb_row)

        # Depth 圖片行
        dep_row = QHBoxLayout()
        self._lbl_dep = QLabel("Depth 圖片：未選擇")
        self._lbl_dep.setWordWrap(True)
        btn_dep = QPushButton("瀏覽…")
        btn_dep.setFixedWidth(80)
        btn_dep.clicked.connect(self._on_browse_depth)
        dep_row.addWidget(self._lbl_dep, 1)
        dep_row.addWidget(btn_dep)
        layout.addLayout(dep_row)

        return group

    def _build_rotation_group(self) -> QGroupBox:
        group = QGroupBox("相機視角控制（套用時請先完成合成）")
        layout = QVBoxLayout(group)

        # Pitch 滑桿
        self._slider_pitch, pitch_row = self._make_slider("Pitch", -45, 45)
        layout.addLayout(pitch_row)

        # Yaw 滑桿
        self._slider_yaw, yaw_row = self._make_slider("Yaw  ", -45, 45)
        layout.addLayout(yaw_row)

        # Roll 滑桿
        self._slider_roll, roll_row = self._make_slider("Roll ", -45, 45)
        layout.addLayout(roll_row)

        # 連接所有滑桿到 Adapter（View 不做矩陣計算）
        for s in (self._slider_pitch, self._slider_yaw, self._slider_roll):
            s.valueChanged.connect(self._on_any_slider_changed)

        return group

    def _build_action_group(self) -> QGroupBox:
        group = QGroupBox("操作")
        layout = QHBoxLayout(group)

        self._btn_synthesize = QPushButton("▶  開始 3D 合成")
        self._btn_synthesize.setFixedHeight(40)
        self._btn_synthesize.clicked.connect(self._on_synthesize_clicked)

        self._btn_stop = QPushButton("■  停止渲染")
        self._btn_stop.setFixedHeight(40)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop_clicked)

        layout.addWidget(self._btn_synthesize)
        layout.addWidget(self._btn_stop)
        return group

    def _build_status_group(self) -> QGroupBox:
        group = QGroupBox("狀態")
        layout = QVBoxLayout(group)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)

        self._lbl_status = QLabel("就緒。請選擇 RGB 與 Depth 圖片後按下「開始 3D 合成」。")
        self._lbl_status.setWordWrap(True)

        layout.addWidget(self._progress_bar)
        layout.addWidget(self._lbl_status)
        return group

    @staticmethod
    def _make_slider(label: str, min_val: int, max_val: int):
        """建立一個帶標籤與數值顯示的水平滑桿，回傳 (QSlider, QHBoxLayout)。"""
        row = QHBoxLayout()
        lbl = QLabel(f"{label}:")
        lbl.setFixedWidth(44)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(min_val, max_val)
        slider.setValue(0)
        val_lbl = QLabel("0°")
        val_lbl.setFixedWidth(36)
        val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # 滑桿數值即時更新顯示
        slider.valueChanged.connect(lambda v, l=val_lbl: l.setText(f"{v}°"))
        row.addWidget(lbl)
        row.addWidget(slider, 1)
        row.addWidget(val_lbl)
        return slider, row

    # ------------------------------------------------------------------
    # GUI 事件處理（View 只做映射，不做計算）
    # ------------------------------------------------------------------

    @Slot()
    def _on_browse_rgb(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇 RGB 圖片", "",
            "圖片檔案 (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self._rgb_path = path
            self._lbl_rgb.setText(f"RGB 圖片：{path}")
            self._update_synthesize_button_state()
            # 通知 Adapter（側邊效果：僅當兩路徑都選好時才發送指令）
            if self._depth_path:
                self._adapter.on_load_files_requested(self._rgb_path, self._depth_path)

    @Slot()
    def _on_browse_depth(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇 Depth 圖片", "",
            "圖片檔案 (*.png *.jpg *.exr *.tiff *.tif)"
        )
        if path:
            self._depth_path = path
            self._lbl_dep.setText(f"Depth 圖片：{path}")
            self._update_synthesize_button_state()
            if self._rgb_path:
                self._adapter.on_load_files_requested(self._rgb_path, self._depth_path)

    @Slot()
    def _on_any_slider_changed(self):
        """任一旋轉滑桿改變 → Adapter 翻譯為旋轉矩陣 → pose_queue。"""
        self._adapter.on_rotation_slider_changed(
            pitch_deg=self._slider_pitch.value(),
            yaw_deg=self._slider_yaw.value(),
            roll_deg=self._slider_roll.value(),
        )

    @Slot()
    def _on_synthesize_clicked(self):
        if self._worker.isRunning():
            return
        if not self._rgb_path or not self._depth_path:
            QMessageBox.warning(self, "缺少輸入", "請先選擇 RGB 圖片與 Depth 圖片。")
            return

        # 啟動渲染子進程（若尚未啟動）
        if not self._render_ctrl.is_alive():
            self._render_ctrl.start_process()

        # 設定檔案路徑並啟動背景執行緒
        self._worker.set_files(self._rgb_path, self._depth_path)
        self._worker.start()

        self._set_controls_enabled(False)
        self._btn_stop.setEnabled(True)
        self._progress_bar.setValue(0)
        self._lbl_status.setText("合成管線啟動中...")

    @Slot()
    def _on_stop_clicked(self):
        """終止渲染子進程。"""
        self._render_ctrl.terminate()
        self._btn_stop.setEnabled(False)
        self._lbl_status.setText("渲染已停止。")
        self._set_controls_enabled(True)

    # ------------------------------------------------------------------
    # 背景執行緒 Signal 接收（Slot）
    # ------------------------------------------------------------------

    @Slot(int, str)
    def _on_progress_updated(self, percent: int, message: str):
        self._progress_bar.setValue(percent)
        self._lbl_status.setText(message)

    @Slot()
    def _on_synthesis_finished(self):
        self._lbl_status.setText("✅ 3D 合成完成！請拖曳滑桿調整視角。")
        self._set_controls_enabled(True)
        self._btn_stop.setEnabled(True)

    @Slot(str)
    def _on_synthesis_failed(self, error_msg: str):
        self._progress_bar.setValue(0)
        self._lbl_status.setText(f"❌ 合成失敗：{error_msg}")
        self._set_controls_enabled(True)
        self._btn_stop.setEnabled(False)
        QMessageBox.critical(self, "合成失敗", f"管線發生錯誤：\n\n{error_msg}")

    # ------------------------------------------------------------------
    # 輔助方法
    # ------------------------------------------------------------------

    def _update_synthesize_button_state(self):
        ready = bool(self._rgb_path) and bool(self._depth_path)
        self._btn_synthesize.setEnabled(ready)

    def _set_controls_enabled(self, enabled: bool):
        """開關可互動控制元件（合成進行中時鎖定，完成後解鎖）。"""
        self._btn_synthesize.setEnabled(
            enabled and bool(self._rgb_path) and bool(self._depth_path)
        )
        for s in (self._slider_pitch, self._slider_yaw, self._slider_roll):
            s.setEnabled(enabled)

    def closeEvent(self, event):
        """視窗關閉時安全終止背景執行緒與渲染子進程。"""
        if self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(3000)
        self._render_ctrl.terminate()
        event.accept()


def run_gui():
    """GUI 應用程式進入點（由 main.py 呼叫）。"""
    app = QApplication(sys.argv)
    app.setApplicationName("3D Photo Synthesis Engine")
    app.setStyle("Fusion")
    window = MainWindowView()
    window.show()
    sys.exit(app.exec())
