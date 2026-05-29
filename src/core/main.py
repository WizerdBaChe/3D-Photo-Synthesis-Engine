"""
3D Photo Synthesis Engine — 應用程式進入點
=============================================
設計依據：DD-011（Portable First，相對路徑啟動）

注意事項：
  - 此檔案必須從專案根目錄執行：python main.py
  - Windows 免安裝環境請使用 run_app.bat（自動設定 PYTHONPATH）
  - multiprocessing 需要在 if __name__ == "__main__" 保護下啟動（Windows spawn 模式）
"""

import logging
import sys
import os

# 確保根目錄在 PYTHONPATH 中（相對路徑啟動保障）
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 設定統一 logging 格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("main")


def main():
    logger.info("3D Photo Synthesis Engine 啟動中...")
    try:
        from gui.main_window import run_gui
        run_gui()
    except ImportError as e:
        logger.error(f"GUI 模組載入失敗：{e}")
        logger.error("請確認已安裝 PySide6：pip install PySide6")
        sys.exit(1)


if __name__ == "__main__":
    # Windows multiprocessing 需要此保護（spawn 模式不同於 fork）
    import multiprocessing
    multiprocessing.freeze_support()
    main()
