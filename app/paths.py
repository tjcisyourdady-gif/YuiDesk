"""统一路径解析，兼容源码开发模式与 PyInstaller 打包模式."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_bundle_dir() -> Path:
    """只读资源目录（web/、内置 skins/ 等）."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def get_app_dir() -> Path:
    """可执行文件所在目录（方便便携版直接放置 skins/ 文件夹）."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    """用户可写数据目录（SQLite 数据库、上传缓存、用户导入皮肤）."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".config"
    data_dir = base / "YuiDesk"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_path() -> Path:
    return get_data_dir() / "yuidesk.db"


def get_uploads_dir() -> Path:
    path = get_data_dir() / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_user_skins_dir() -> Path:
    path = get_data_dir() / "skins"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_portable_skins_dir() -> Path:
    path = get_app_dir() / "skins"
    return path


def get_web_dir() -> Path:
    return get_bundle_dir() / "web"
