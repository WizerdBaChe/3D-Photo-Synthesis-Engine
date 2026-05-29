"""
獨立渲染管線 (Independent Rendering Pipeline)
================================================
設計依據：PSM Phase 5、DD-003（Queue 非同步通訊）、PSM Phase 7（進程邊界）

進程邊界（PSM Phase 7）：
  主進程（PySide6 GUI + AI Worker QThread）
      │
      │  multiprocessing.Queue（IPC）
      ▼
  子進程（Open3DRenderWorker）—— 獨佔 Open3D Visualizer 視窗

規範：
  - Open3DRenderWorker 嚴禁 import 任何 PySide6/PyQt 模組。
  - 大型 3D Mesh 不透過 Queue 傳遞，僅傳遞 .ply 檔案路徑（Red Line 4）。
  - RenderProcessController 提供最新優先 (Latest-Wins) 的位姿更新策略。
"""

from __future__ import annotations
import logging
import queue as stdlib_queue
import multiprocessing as mp

import open3d as o3d
import numpy as np

from src.app.commands import MeshLoadCommand, CameraPoseCommand, ShutdownCommand

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 子進程渲染器（Open3D 側）
# ---------------------------------------------------------------------------

class Open3DRenderWorker:
    """
    Open3D 渲染工作者，運行於獨立 OS Process（PSM Phase 5.4）。

    生命週期：
      run() 進入點 → 建立 Visualizer 視窗 → 事件迴圈 → 收到 ShutdownCommand → 銷毀視窗
    """

    def __init__(self, command_queue: mp.Queue):
        self.command_queue = command_queue
        self.vis:  o3d.visualization.Visualizer = None
        self.mesh: o3d.geometry.TriangleMesh    = None

    def run(self):
        """子進程進入點：建立視窗並進入事件迴圈。"""
        self.vis = o3d.visualization.Visualizer()
        self.vis.create_window(
            window_name="3D Photo Synthesis Engine — Render View",
            width=1280, height=720
        )

        # 預設場景：座標軸示意物件（避免首幀空場景崩潰）
        coord_frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=0.5)
        self.vis.add_geometry(coord_frame)

        is_running = True
        while is_running:
            # 非阻塞讀取指令（不阻塞渲染迴圈）
            try:
                cmd = self.command_queue.get_nowait()
                is_running = self._handle_command(cmd)
            except stdlib_queue.Empty:
                pass

            # Open3D 視窗事件輪詢（視窗被手動關閉時 poll_events 回傳 False）
            if not self.vis.poll_events():
                break

            self.vis.update_renderer()

        self.vis.destroy_window()

    def _handle_command(self, cmd) -> bool:
        """
        依指令類型分派處理。
        回傳 False 代表需要關閉渲染迴圈。
        """
        if isinstance(cmd, ShutdownCommand):
            return False

        if isinstance(cmd, MeshLoadCommand):
            self._load_mesh_from_file(cmd.mesh_filepath)

        elif isinstance(cmd, CameraPoseCommand):
            self._update_camera_pose(cmd.extrinsic_matrix)

        return True

    def _load_mesh_from_file(self, filepath: str):
        """從 .ply 暫存檔載入新網格，替換場景中的舊網格。"""
        new_mesh = o3d.io.read_triangle_mesh(filepath)
        if not new_mesh.has_vertices():
            logger.warning(f"網格檔案為空或讀取失敗：{filepath}")
            return

        if self.mesh is not None:
            self.vis.remove_geometry(self.mesh, reset_bounding_box=False)

        self.mesh = new_mesh
        self.vis.add_geometry(self.mesh)
        self.vis.reset_view_point(True)

    def _update_camera_pose(self, extrinsic_matrix: np.ndarray):
        """套用 4×4 外參矩陣更新虛擬相機視角。"""
        ctr        = self.vis.get_view_control()
        cam_params = ctr.convert_to_pinhole_camera_parameters()
        cam_params.extrinsic = extrinsic_matrix
        ctr.convert_from_pinhole_camera_parameters(cam_params)
        self.vis.update_renderer()


def _render_process_entry(command_queue: mp.Queue):
    """
    頂層函式，作為 multiprocessing.Process 的 target。
    必須為模組頂層函式（multiprocessing spawn 模式的限制）。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="[RenderProcess] %(asctime)s [%(levelname)s] %(message)s"
    )
    worker = Open3DRenderWorker(command_queue)
    worker.run()


# ---------------------------------------------------------------------------
# 主進程控制器
# ---------------------------------------------------------------------------

class RenderProcessController:
    """
    主進程側渲染控制器（PSM Phase 5.3）。

    提供統一的介面，讓 Orchestrator 與 GUI 無需關心子進程細節。

    位姿更新策略：Latest-Wins
      當使用者快速拖曳滑桿時，舊的 CameraPoseCommand 會被丟棄，
      只保留最新的位姿指令，避免佇列堆積與延遲。
    """

    def __init__(self):
        self.command_queue:  mp.Queue  = mp.Queue()
        self.render_process: mp.Process = None

    def start_process(self):
        """啟動 Open3D 渲染子進程。"""
        if self.is_alive():
            logger.warning("渲染進程已在運行，忽略重複啟動請求。")
            return

        self.render_process = mp.Process(
            target=_render_process_entry,
            args=(self.command_queue,),
            daemon=True,
            name="Open3DRenderProcess"
        )
        self.render_process.start()
        logger.info(f"渲染子進程已啟動，PID: {self.render_process.pid}")

    def is_alive(self) -> bool:
        """檢查子進程是否仍在運行。"""
        return self.render_process is not None and self.render_process.is_alive()

    def load_mesh(self, mesh_filepath: str):
        """通知渲染器載入新的 3D 網格（傳遞 .ply 路徑，不傳 Mesh 物件）。"""
        self.command_queue.put(MeshLoadCommand(mesh_filepath=mesh_filepath))

    def update_camera(self, extrinsic_matrix: np.ndarray):
        """
        通知渲染器更新相機視角（Latest-Wins 策略）。
        在 put 新指令前，清空佇列中已堆積的舊 CameraPoseCommand，
        避免 GUI 高頻拖曳時位姿指令累積造成渲染延遲。
        """
        # 清空舊的位姿指令（其他類型指令放回）
        drained_others = []
        while True:
            try:
                item = self.command_queue.get_nowait()
                if not isinstance(item, CameraPoseCommand):
                    drained_others.append(item)
            except stdlib_queue.Empty:
                break
        for item in drained_others:
            self.command_queue.put(item)

        self.command_queue.put(CameraPoseCommand(extrinsic_matrix=extrinsic_matrix))

    def terminate(self):
        """
        安全終止渲染子進程：
          1. 發送 ShutdownCommand（讓子進程有機會正常退出）
          2. 等待最多 5 秒
          3. 若超時則強制 terminate()
        """
        if not self.is_alive():
            return

        self.command_queue.put(ShutdownCommand())
        self.render_process.join(timeout=5.0)

        if self.is_alive():
            logger.warning("渲染子進程未能在 5 秒內正常關閉，強制終止。")
            self.render_process.terminate()
            self.render_process.join(timeout=2.0)
