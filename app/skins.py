"""桌宠皮肤包（Skin Pack）加载与一键导入系统."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from app.paths import get_bundle_dir, get_portable_skins_dir, get_user_skins_dir

PET_STATES = [
    "idle",
    "idle_blink",
    "hover",
    "drag",
    "file_catch",
    "eat_open",
    "eat_chew",
    "inspect_file",
    "thinking",
    "searching",
    "reading",
    "speaking",
    "happy",
    "error",
    "sleep",
    "tea",
    "peek_left",
    "peek_right",
    "pet_head",
    "eat_cake",
    "practice_guitar",
    "study_desk",
    "hungry",
    "stretch",
    "walk_left",
    "walk_right",
    "sit_swing",
    "music_dance",
    "shy_blush",
    "proud_pose",
]

IMAGE_SUFFIXES = (".gif", ".png", ".webp", ".svg", ".jpg", ".jpeg")


def _search_roots() -> list[tuple[Path, str]]:
    """按优先级返回皮肤搜索目录（用户导入 > 便携目录 skins/ > 安装包内置 skins/）."""
    roots: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for path, source in [
        (get_user_skins_dir(), "user"),
        (get_portable_skins_dir(), "portable"),
        (get_bundle_dir() / "skins", "builtin"),
    ]:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen and path.exists():
            seen.add(key)
            roots.append((path, source))
    return roots


def _resolve_state_assets(skin_dir: Path, declared_states: dict[str, str]) -> dict[str, str]:
    """解析每个状态对应的本地绝对图片路径，支持单图自动兜底."""
    resolved: dict[str, str] = {}

    # 1. 先按 skin.json 显式声明查找
    for state, rel in declared_states.items():
        if not rel:
            continue
        candidate = skin_dir / rel
        if candidate.is_file():
            resolved[state] = str(candidate)

    # 2. 按文件名约定自动发现（idle.gif / idle.png / thinking.gif ...）
    for state in PET_STATES:
        if state in resolved:
            continue
        for ext in IMAGE_SUFFIXES:
            candidate = skin_dir / f"{state}{ext}"
            if candidate.is_file():
                resolved[state] = str(candidate)
                break

    # 3. 兼容“单图秒活模式”：若目录下只有任意一张图（如 yui.png / cover.png），自动作为 idle
    if "idle" not in resolved:
        for file in sorted(skin_dir.iterdir()):
            if file.is_file() and file.suffix.lower() in IMAGE_SUFFIXES:
                resolved["idle"] = str(file)
                break

    return resolved


def load_skin_from_dir(skin_dir: Path, source: str = "user") -> dict[str, Any] | None:
    if not skin_dir.is_dir():
        return None
    meta_path = skin_dir / "skin.json"
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    skin_id = str(meta.get("id") or skin_dir.name)
    declared_states = meta.get("states") if isinstance(meta.get("states"), dict) else {}
    assets = _resolve_state_assets(skin_dir, declared_states)
    render_mode = meta.get("render_mode") or ("image" if assets else "builtin_vector")

    return {
        "id": skin_id,
        "name": meta.get("name") or skin_dir.name,
        "author": meta.get("author") or "自定义",
        "description": meta.get("description") or "",
        "source": source,
        "dir": str(skin_dir),
        "render_mode": render_mode,
        "has_custom_images": bool(assets),
        "assets": assets,
        "accent_color": meta.get("accent_color") or "#FF7A59",
        "size_multiplier": float(meta.get("size_multiplier") or 1.0),
        "default_persona_id": meta.get("default_persona_id") or "",
        "file_anchors": meta.get("file_anchors") if isinstance(meta.get("file_anchors"), dict) else {},
        "state_labels": meta.get("state_labels") if isinstance(meta.get("state_labels"), dict) else {},
        "care_overrides": meta.get("care_overrides") if isinstance(meta.get("care_overrides"), dict) else {},
        "bubbles": meta.get("bubbles") or {
            "idle": [
                "今天也要元气满满哦~ ✨",
                "有什么文档或问题，直接拖给我吧！",
                "按 Alt+Space 随时叫醒我~",
            ],
            "happy": ["搞定啦！还需要我帮忙吗？✨"],
            "error": ["呜哇，好像连不上 API 了，点我看看设置吧~"],
            "sleep": ["Zzz... 稍微打个盹，有事随时叫我哦~"],
        },
    }


def list_skins() -> list[dict[str, Any]]:
    skins: dict[str, dict[str, Any]] = {}
    # 后加载覆盖前加载不合适；按优先级：user > portable > builtin，先发现的保留
    for root, source in _search_roots():
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            skin = load_skin_from_dir(child, source=source)
            if skin and skin["id"] not in skins:
                skins[skin["id"]] = skin

    result = list(skins.values())
    # 内置主角色排在前面（艾露猫 -> 巨型哥斯拉 -> 轻音少女 -> 四足小狐狸 -> Q版小狐狸 -> 模板 -> 自定义）
    order_map = {"palico": 0, "godzilla": 1, "default_sprite": 2, "fox_animal": 3, "little_fox": 4, "yui_template": 5}
    result.sort(key=lambda s: (order_map.get(s["id"], 6), s["name"]))
    return result


def get_skin(skin_id: str) -> dict[str, Any]:
    skins = list_skins()
    for s in skins:
        if s["id"] == skin_id:
            return s
    if skins:
        return skins[0]
    return {
        "id": "default_sprite",
        "name": "轻音星灵（原创默认）",
        "author": "YuiDesk",
        "description": "原创矢量萌宠",
        "source": "builtin",
        "dir": "",
        "render_mode": "builtin_vector",
        "has_custom_images": False,
        "assets": {},
        "accent_color": "#FF7A59",
        "default_persona_id": "assistant",
        "bubbles": {"idle": ["你好呀！点击我就可以开始聊天~"]},
    }


def import_skin_from_zip(zip_bytes: bytes, filename: str) -> dict[str, Any]:
    """导入用户上传的 .zip 皮肤包到用户 skins/ 目录."""
    import io

    stem = Path(filename).stem.strip() or "custom_skin"
    safe_id = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in stem).lower() or "custom_skin"
    target_dir = get_user_skins_dir() / safe_id
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        members = [m for m in zf.namelist() if not m.endswith("/") and ".." not in m]
        # 若压缩包内所有文件都在同一个顶层子文件夹中，自动剥离一层
        top_dirs = {Path(m).parts[0] for m in members if len(Path(m).parts) > 1}
        strip_prefix = len(top_dirs) == 1 and all(len(Path(m).parts) > 1 for m in members)
        for member in members:
            parts = Path(member).parts[1:] if strip_prefix else Path(member).parts
            if not parts:
                continue
            dest = target_dir / Path(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)

    skin = load_skin_from_dir(target_dir, source="user")
    if not skin:
        raise ValueError("压缩包中未检测到有效的皮肤内容")
    return skin


def import_single_image_skin(image_bytes: bytes, filename: str, skin_name: str = "") -> dict[str, Any]:
    """单图一键生成皮肤（例如直接上传一张平泽唯透明 PNG/GIF）."""
    ext = Path(filename).suffix.lower()
    if ext not in IMAGE_SUFFIXES:
        raise ValueError(f"不支持的图片格式：{ext}（支持 PNG / GIF / WebP）")
    display_name = skin_name.strip() or Path(filename).stem or "自定义角色"
    safe_id = f"custom_{abs(hash(display_name)) % 100000}"
    target_dir = get_user_skins_dir() / safe_id
    target_dir.mkdir(parents=True, exist_ok=True)

    idle_file = target_dir / f"idle{ext}"
    idle_file.write_bytes(image_bytes)

    meta = {
        "id": safe_id,
        "name": display_name,
        "author": "用户导入",
        "description": "单图自动呼吸动效 + 状态挂件特效",
        "render_mode": "image",
        "accent_color": "#FF7A59",
        "default_persona_id": "yui_cheerful",
        "bubbles": {
            "idle": [
                "下午茶时间到啦~ 有什么需要我帮忙吗？☕",
                "把文件直接拖到我身上就可以帮你读哦！",
                "按 Alt+Space 随时叫醒我~ 🎸",
            ],
            "happy": ["耶！搞定啦~ ✨"],
            "error": ["唔…好像哪里出错了，点我检查下 API 设置吧💦"],
            "sleep": ["Zzz... 软绵绵的真舒服…有事叫我哦~"],
        },
    }
    (target_dir / "skin.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    skin = load_skin_from_dir(target_dir, source="user")
    assert skin is not None
    return skin
