"""ui - 可视化层包"""
from .heatmap import HeatmapVisualizer
from .report import CLIReport
from .image_renderer import ImageRenderer

# create_app 来自可选的 FastAPI 服务 (ui/server.py).
# 该文件当前不存在 —— Web GUI 已改用 scripts/pick_gui.py (Flask).
# 保留可选导入, 避免整个包因缺失模块而无法 import.
try:  # pragma: no cover
    from .server import create_app  # type: ignore
except ImportError:
    create_app = None  # type: ignore

__all__ = ["HeatmapVisualizer", "CLIReport", "create_app", "ImageRenderer"]
