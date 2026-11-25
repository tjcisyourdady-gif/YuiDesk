"""YuiDesk 安全自动更新引擎：支持 GitHub 官方源 + 国内加速镜像回退 + 强制 SHA-256 校验 + Zip-Slip 防护."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.paths import get_app_dir, get_data_dir, is_frozen
from app.version import (
    APP_NAME,
    APP_VERSION,
    GITHUB_BRANCH,
    GITHUB_OWNER,
    GITHUB_REPO,
    GITHUB_RELEASES_URL,
    GITHUB_REPO_URL,
)

# 仅允许更新以下合法白名单路径（防止压缩包覆盖无关系统文件）
ALLOWED_TOP_LEVEL_ENTRIES = {
    "YuiDesk.exe",
    "_internal",
    "skins",
    "kimi_engine",
    "使用说明.txt",
    "使用手册.md",
}

# 国内加速下载代理（仅在 GitHub 直连超时/失败时作为下载通道回退；所有下载包都必须通过官方 SHA-256 严格校验！）
CHINA_DOWNLOAD_PROXIES = (
    "https://ghfast.top/",
    "https://gh-proxy.com/",
    "https://mirror.ghproxy.com/",
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def parse_version(ver: str) -> tuple[int, ...]:
    """将语义化版本号（如 'v1.2.0' 或 '1.2.3'）转为可比较元组."""
    cleaned = str(ver or "").strip().lstrip("vV")
    nums = [int(x) for x in re.findall(r"\d+", cleaned)]
    return tuple(nums) if nums else (0,)


def is_newer_version(remote: str, current: str = APP_VERSION) -> bool:
    r = parse_version(remote)
    c = parse_version(current)
    max_len = max(len(r), len(c))
    r_pad = r + (0,) * (max_len - len(r))
    c_pad = c + (0,) * (max_len - len(c))
    return r_pad > c_pad


def _is_trusted_release_url(url: str) -> bool:
    """严格校验下载地址必须指向本项目的 HTTPS GitHub Release."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme != "https":
        return False
    expected_prefix = f"/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/".lower()
    return parsed.netloc.lower() == "github.com" and parsed.path.lower().startswith(expected_prefix)


def _validate_sha256_str(val: str) -> bool:
    return bool(SHA256_RE.match(str(val or "").strip().lower()))


def compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().lower()


def _safe_extract_zip(zip_path: Path, stage_dir: Path) -> list[str]:
    """带 Zip-Slip 路径穿越防护与白名单校验的安全解压."""
    if stage_dir.exists():
        shutil.rmtree(stage_dir, ignore_errors=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_resolved = stage_dir.resolve()

    extracted: list[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        infos = zf.infolist()
        if not infos:
            raise ValueError("更新包为空")

        # 兼容顶层包了一层 YuiDesk/ 目录的情况
        top_names = {
            PurePosixParts[0]
            for info in infos
            for PurePosixParts in [[p for p in info.filename.replace("\\", "/").split("/") if p]]
            if PurePosixParts
        }
        strip_root = len(top_names) == 1 and next(iter(top_names)).lower() == APP_NAME.lower()

        for info in infos:
            raw_name = info.filename.replace("\\", "/")
            if raw_name.startswith("/") or re.match(r"^[a-zA-Z]:", raw_name):
                raise ValueError(f"更新包包含非法绝对路径：{info.filename}")
            parts = [p for p in raw_name.split("/") if p and p != "."]
            if not parts:
                continue
            if any(p == ".." for p in parts):
                raise ValueError(f"更新包包含非法上级目录穿越：{info.filename}")
            if strip_root:
                parts = parts[1:]
                if not parts:
                    continue
            if parts[0] not in ALLOWED_TOP_LEVEL_ENTRIES:
                raise ValueError(f"更新包包含未授权的文件路径：{parts[0]}")

            target = (stage_dir / Path(*parts)).resolve()
            if not target.is_relative_to(stage_resolved):
                raise ValueError(f"更新包解压路径越界：{info.filename}")

            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted.append("/".join(parts))

    if not extracted:
        raise ValueError("更新包未包含任何有效文件")
    return extracted


class UpdateManager:
    """管理版本检查、进度下载、SHA-256 校验与重启应用更新."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "current_version": APP_VERSION,
            "repo_url": GITHUB_REPO_URL,
            "releases_url": GITHUB_RELEASES_URL,
            "is_frozen": is_frozen(),
            "status": "idle",  # idle | checking | available | up_to_date | downloading | ready | error
            "has_update": False,
            "latest_version": "",
            "released_at": "",
            "notes": "",
            "package_kind": "patch",  # patch | full
            "package_filename": "",
            "package_url": "",
            "package_sha256": "",
            "package_size": 0,
            "metadata_source": "",
            "download_source": "",
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "progress_pct": 0,
            "staged_dir": "",
            "message": "",
            "checked_at": 0.0,
        }
        self._download_thread: threading.Thread | None = None

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def _update_state(self, **kwargs: Any) -> dict[str, Any]:
        with self._lock:
            self._state.update(kwargs)
            return dict(self._state)

    def _fetch_manifest(self) -> tuple[dict[str, Any], str]:
        """依次尝试官方 GitHub 与国内 CDN 镜像拉取 latest.json 更新清单."""
        headers = {
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
            "Accept": "application/json",
        }
        # 1. 优先尝试官方 GitHub Releases API（最权威），失败则回退 raw / 国内 jsDelivr CDN
        candidates = [
            ("github_api", f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"),
            ("github_raw", f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/latest.json"),
            ("jsdelivr_cdn", f"https://cdn.jsdelivr.net/gh/{GITHUB_OWNER}/{GITHUB_REPO}@{GITHUB_BRANCH}/latest.json"),
            ("fastly_cdn", f"https://fastly.jsdelivr.net/gh/{GITHUB_OWNER}/{GITHUB_REPO}@{GITHUB_BRANCH}/latest.json"),
        ]
        errors: list[str] = []

        with httpx.Client(timeout=httpx.Timeout(8.0, connect=5.0), follow_redirects=True, headers=headers) as client:
            for source_name, url in candidates:
                try:
                    resp = client.get(url)
                    if resp.status_code != 200:
                        errors.append(f"{source_name}: HTTP {resp.status_code}")
                        continue
                    data = resp.json()
                    if source_name == "github_api" and isinstance(data, dict) and "tag_name" in data:
                        manifest = self._parse_github_release_api(client, data)
                        if manifest:
                            return manifest, "GitHub 官方 Release"
                        errors.append("github_api: 未解析到有效资产")
                        continue
                    if isinstance(data, dict) and data.get("version"):
                        label = {
                            "github_raw": "GitHub 官方清单",
                            "jsdelivr_cdn": "jsDelivr 国内镜像",
                            "fastly_cdn": "Fastly 国内镜像",
                        }.get(source_name, source_name)
                        return data, label
                except Exception as exc:
                    errors.append(f"{source_name}: {exc}")

        raise RuntimeError("无法连接到更新服务器（已尝试 GitHub 与国内镜像）：" + "; ".join(errors[:3]))

    def _parse_github_release_api(self, client: httpx.Client, rel: dict[str, Any]) -> dict[str, Any] | None:
        assets = rel.get("assets") if isinstance(rel.get("assets"), list) else []
        # 若 Release 附带了 latest.json，直接读取其中的 SHA-256 清单
        for a in assets:
            if isinstance(a, dict) and str(a.get("name") or "").lower() == "latest.json":
                dl = str(a.get("browser_download_url") or "")
                if dl and _is_trusted_release_url(dl):
                    try:
                        r2 = client.get(dl)
                        if r2.status_code == 200:
                            j = r2.json()
                            if isinstance(j, dict) and j.get("version"):
                                return j
                    except Exception:
                        pass
        # 兜底：从 Release 正文解析 SHA-256（格式：SHA256(YuiDesk_patch.zip)=<64hex>）
        body = str(rel.get("body") or "")
        version = str(rel.get("tag_name") or "").lstrip("vV")
        if not version:
            return None
        manifest: dict[str, Any] = {
            "version": version,
            "released_at": str(rel.get("published_at") or "")[:10],
            "notes": body.strip(),
        }
        for a in assets:
            if not isinstance(a, dict):
                continue
            name = str(a.get("name") or "")
            dl = str(a.get("browser_download_url") or "")
            size = int(a.get("size") or 0)
            m_hash = re.search(rf"SHA256\({re.escape(name)}\)\s*[:=]\s*([0-9a-fA-F]{{64}})", body)
            sha = m_hash.group(1).lower() if m_hash else ""
            if "patch" in name.lower() and name.lower().endswith(".zip"):
                manifest["patch"] = {"filename": name, "url": dl, "sha256": sha, "size_bytes": size}
            elif name.lower().endswith(".zip"):
                manifest["full"] = {"filename": name, "url": dl, "sha256": sha, "size_bytes": size}
        return manifest

    def check_for_updates(self) -> dict[str, Any]:
        cur = self.get_status()
        if cur["status"] == "downloading":
            return cur

        self._update_state(status="checking", message="正在检查更新...")
        try:
            manifest, source_label = self._fetch_manifest()
            remote_ver = str(manifest.get("version") or "").strip().lstrip("vV")
            if not remote_ver:
                raise RuntimeError("更新清单缺少版本号")

            has_update = is_newer_version(remote_ver, APP_VERSION)
            min_patch = str(manifest.get("min_patch_version") or "1.0.0")
            can_patch = not is_newer_version(min_patch, APP_VERSION)

            pkg_kind = "patch"
            pkg = manifest.get("patch") if (can_patch and isinstance(manifest.get("patch"), dict)) else None
            if not pkg or not pkg.get("url"):
                pkg_kind = "full"
                pkg = manifest.get("full") if isinstance(manifest.get("full"), dict) else {}

            pkg_url = str(pkg.get("url") or "").strip()
            pkg_sha = str(pkg.get("sha256") or "").strip().lower()
            pkg_size = int(pkg.get("size_bytes") or 0)
            pkg_name = str(pkg.get("filename") or ("YuiDesk_patch.zip" if pkg_kind == "patch" else "YuiDesk_便携版.zip"))

            if has_update:
                if not _is_trusted_release_url(pkg_url):
                    raise RuntimeError("更新清单中的下载地址不在官方仓库白名单内，已拒绝")
                if not _validate_sha256_str(pkg_sha):
                    raise RuntimeError("更新清单缺少合法的 SHA-256 校验值，已拒绝不安全的更新")

            msg = (
                f"发现新版本 v{remote_ver}（当前 v{APP_VERSION}），点击即可安全下载更新"
                if has_update
                else f"当前已是最新版本 v{APP_VERSION}"
            )
            return self._update_state(
                status="available" if has_update else "up_to_date",
                has_update=has_update,
                latest_version=remote_ver,
                released_at=str(manifest.get("released_at") or ""),
                notes=str(manifest.get("notes") or "").strip(),
                package_kind=pkg_kind,
                package_filename=pkg_name,
                package_url=pkg_url,
                package_sha256=pkg_sha,
                package_size=pkg_size,
                metadata_source=source_label,
                message=msg,
                checked_at=time.time(),
            )
        except Exception as exc:
            return self._update_state(
                status="error",
                has_update=False,
                message=str(exc),
                checked_at=time.time(),
            )

    def start_download(self) -> dict[str, Any]:
        st = self.get_status()
        if st["status"] == "downloading":
            return st
        if not st.get("has_update") or not st.get("package_url") or not st.get("package_sha256"):
            st = self.check_for_updates()
            if not st.get("has_update"):
                return st

        pkg_url = st["package_url"]
        expected_sha = st["package_sha256"]
        if not _is_trusted_release_url(pkg_url) or not _validate_sha256_str(expected_sha):
            return self._update_state(status="error", message="更新包地址或 SHA-256 校验参数非法，已拒绝下载")

        self._update_state(
            status="downloading",
            downloaded_bytes=0,
            total_bytes=int(st.get("package_size") or 0),
            progress_pct=0,
            staged_dir="",
            download_source="",
            message="正在连接下载节点...",
        )

        def _worker() -> None:
            updates_root = get_data_dir() / "updates"
            updates_root.mkdir(parents=True, exist_ok=True)
            ver_tag = re.sub(r"[^0-9A-Za-z._-]", "_", st["latest_version"] or "latest")
            zip_dest = updates_root / f"update_{ver_tag}.zip"
            stage_dir = updates_root / f"staging_{ver_tag}"

            # 依次尝试官方 GitHub 直连与国内代理通道（所有通道都必须通过同一个官方 SHA-256 校验！）
            urls_to_try: list[tuple[str, str]] = [("GitHub 官方直连", pkg_url)]
            for prefix in CHINA_DOWNLOAD_PROXIES:
                host = urlparse(prefix).netloc
                urls_to_try.append((f"国内加速镜像 ({host})", prefix + pkg_url))

            last_err = ""
            verified_ok = False
            used_source = ""
            headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION}"}

            for source_label, dl_url in urls_to_try:
                self._update_state(
                    download_source=source_label,
                    downloaded_bytes=0,
                    progress_pct=0,
                    message=f"正在通过 {source_label} 下载更新包...",
                )
                tmp_path = zip_dest.with_suffix(".part")
                try:
                    if tmp_path.exists():
                        tmp_path.unlink(missing_ok=True)
                    with httpx.Client(
                        timeout=httpx.Timeout(30.0, connect=8.0),
                        follow_redirects=True,
                        headers=headers,
                    ) as client:
                        with client.stream("GET", dl_url) as resp:
                            if resp.status_code != 200:
                                last_err = f"{source_label} 返回 HTTP {resp.status_code}"
                                continue
                            total = int(resp.headers.get("content-length") or st.get("package_size") or 0)
                            done = 0
                            hasher = hashlib.sha256()
                            with tmp_path.open("wb") as fp:
                                for chunk in resp.iter_bytes(chunk_size=131072):
                                    if not chunk:
                                        continue
                                    fp.write(chunk)
                                    hasher.update(chunk)
                                    done += len(chunk)
                                    pct = int(min(99, round(done * 100 / total))) if total > 0 else 0
                                    self._update_state(
                                        downloaded_bytes=done,
                                        total_bytes=total,
                                        progress_pct=pct,
                                    )

                    actual_sha = hasher.hexdigest().lower()
                    if actual_sha != expected_sha:
                        tmp_path.unlink(missing_ok=True)
                        last_err = f"{source_label} 校验失败（SHA-256 不匹配，已自动丢弃该节点文件）"
                        continue

                    if zip_dest.exists():
                        zip_dest.unlink(missing_ok=True)
                    tmp_path.replace(zip_dest)
                    verified_ok = True
                    used_source = source_label
                    break
                except Exception as exc:
                    tmp_path.unlink(missing_ok=True)
                    last_err = f"{source_label}: {exc}"

            if not verified_ok:
                self._update_state(
                    status="error",
                    message=f"下载或安全校验失败：{last_err}",
                )
                return

            try:
                self._update_state(progress_pct=99, message="SHA-256 完整性校验通过，正在安全解压更新包...")
                extracted = _safe_extract_zip(zip_dest, stage_dir)
                zip_dest.unlink(missing_ok=True)
                self._update_state(
                    status="ready",
                    progress_pct=100,
                    staged_dir=str(stage_dir),
                    download_source=used_source,
                    message=f"v{st['latest_version']} 已下载并校验通过（{len(extracted)} 个文件），点击「安装并重启」即可完成更新",
                )
            except Exception as exc:
                shutil.rmtree(stage_dir, ignore_errors=True)
                zip_dest.unlink(missing_ok=True)
                self._update_state(status="error", message=f"更新包解压校验失败：{exc}")

        self._download_thread = threading.Thread(target=_worker, daemon=True)
        self._download_thread.start()
        return self.get_status()

    def apply_staged_update(self) -> dict[str, Any]:
        """在便携版运行状态下，生成脱离进程的安全替换脚本并准备重启（不触碰 %APPDATA% 用户数据）."""
        st = self.get_status()
        stage_str = str(st.get("staged_dir") or "")
        if st["status"] != "ready" or not stage_str or not Path(stage_str).is_dir():
            return {"ok": False, "message": "尚未下载并校验好可用的更新包，请先点击下载更新。"}

        if not is_frozen():
            return {
                "ok": False,
                "message": "当前为源码开发运行模式，已跳过覆盖源码目录。请直接在打包后的 YuiDesk.exe 中执行自动安装更新。",
            }
        if os.name != "nt":
            return {"ok": False, "message": "当前自动覆盖重启仅支持 Windows 便携版。"}

        app_dir = get_app_dir().resolve()
        exe_path = app_dir / f"{APP_NAME}.exe"
        stage_dir = Path(stage_str).resolve()
        updates_root = get_data_dir() / "updates"
        script_path = updates_root / "apply_update.ps1"
        pid = os.getpid()

        # 使用单引号安全转义路径，避免 PowerShell 命令注入
        def _ps_quote(s: str) -> str:
            return "'" + s.replace("'", "''") + "'"

        script_content = (
            "$ErrorActionPreference = 'SilentlyContinue'\n"
            f"$targetPid = {pid}\n"
            f"$stageDir = {_ps_quote(str(stage_dir))}\n"
            f"$appDir = {_ps_quote(str(app_dir))}\n"
            f"$exePath = {_ps_quote(str(exe_path))}\n"
            "for ($i = 0; $i -lt 40; $i++) {\n"
            "    if (-not (Get-Process -Id $targetPid -ErrorAction SilentlyContinue)) { break }\n"
            "    Start-Sleep -Milliseconds 500\n"
            "}\n"
            "Start-Sleep -Milliseconds 400\n"
            "if (Test-Path $stageDir) {\n"
            "    Copy-Item -Path (Join-Path $stageDir '*') -Destination $appDir -Recurse -Force\n"
            "    Remove-Item -Path $stageDir -Recurse -Force -ErrorAction SilentlyContinue\n"
            "}\n"
            "if (Test-Path $exePath) {\n"
            "    Start-Process -FilePath $exePath -WorkingDirectory $appDir\n"
            "}\n"
        )
        script_path.write_text(script_content, encoding="utf-8-sig")

        flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(script_path),
            ],
            creationflags=flags,
            close_fds=True,
        )
        return {
            "ok": True,
            "restarting": True,
            "message": "正在应用更新并自动重启 YuiDesk...",
        }
