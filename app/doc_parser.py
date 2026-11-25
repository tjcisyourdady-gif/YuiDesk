"""双通道文档解析、图片处理与网页链接正文提取."""

from __future__ import annotations

import base64
import io
import mimetypes
import re
import uuid
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from PIL import Image

from app.paths import get_uploads_dir

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".csv", ".tsv", ".xml", ".html", ".htm", ".css", ".js", ".ts", ".jsx", ".tsx",
    ".py", ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs", ".php", ".rb",
    ".sh", ".ps1", ".bat", ".sql", ".log", ".vue", ".svelte",
}
URL_REGEX = re.compile(r"https?://[^\s<>\"'`\])】）]+")
MAX_EXTRACTED_CHARS = 120_000


def detect_urls(text: str) -> list[str]:
    urls = URL_REGEX.findall(text or "")
    seen: list[str] = []
    for u in urls:
        cleaned = u.rstrip(".,;:!?，。；：！？")
        if cleaned not in seen:
            seen.append(cleaned)
    return seen[:3]


async def fetch_webpage_text(url: str, timeout: float = 12.0) -> dict[str, Any]:
    """抓取网页正文（复刻 Kimi 粘贴链接直读）."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return {"url": url, "title": url, "text": "", "error": f"非网页文本类型: {content_type}"}
            soup = BeautifulSoup(resp.text, "html.parser")
            title = (soup.title.string.strip() if soup.title and soup.title.string else url)
            for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "aside"]):
                tag.decompose()
            raw_text = soup.get_text(separator="\n")
            lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
            text = "\n".join(lines)[:25_000]
            return {"url": url, "title": title, "text": text, "chars": len(text)}
    except Exception as exc:
        return {"url": url, "title": url, "text": "", "error": str(exc)}


def _extract_pdf_local(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for idx, page in enumerate(reader.pages, start=1):
        txt = (page.extract_text() or "").strip()
        if txt:
            parts.append(f"--- 第 {idx} 页 ---\n{txt}")
    return "\n\n".join(parts)


def _extract_docx_local(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    parts: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        rows = []
        for row in table.rows:
            rows.append(" | ".join(cell.text.strip().replace("\n", " ") for cell in row.cells))
        if rows:
            parts.append("\n".join(rows))
    return "\n\n".join(parts)


def _extract_xlsx_local(data: bytes) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    parts: list[str] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows: list[str] = []
        for idx, row in enumerate(ws.iter_rows(values_only=True)):
            if idx >= 500:
                rows.append("... (超出 500 行已截断)")
                break
            vals = ["" if v is None else str(v) for v in row]
            if any(v.strip() for v in vals):
                rows.append(" | ".join(vals))
        if rows:
            parts.append(f"### 工作表: {sheet_name}\n" + "\n".join(rows))
    wb.close()
    return "\n\n".join(parts)


def _extract_pptx_local(data: bytes) -> str:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    parts: list[str] = []
    for idx, slide in enumerate(prs.slides, start=1):
        texts = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                t = shape.text_frame.text.strip()
                if t:
                    texts.append(t)
        if texts:
            parts.append(f"--- 幻灯片 {idx} ---\n" + "\n".join(texts))
    return "\n\n".join(parts)


def extract_document_local(filename: str, data: bytes) -> str:
    """本地通用文档文本提取（支持所有 API 供应商）."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        text = _extract_pdf_local(data)
    elif ext == ".docx":
        text = _extract_docx_local(data)
    elif ext in (".xlsx", ".xlsm"):
        text = _extract_xlsx_local(data)
    elif ext == ".pptx":
        text = _extract_pptx_local(data)
    elif ext in TEXT_EXTS or not ext:
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = data.decode("utf-8", errors="replace")
    else:
        # 兜底尝试按文本解码
        text = data.decode("utf-8", errors="ignore")
    return text[:MAX_EXTRACTED_CHARS]


async def extract_document_via_kimi(
    base_url: str,
    api_key: str,
    filename: str,
    data: bytes,
    timeout: float = 45.0,
) -> str:
    """使用 Moonshot 官方 /v1/files (purpose=file-extract) 解析文档."""
    headers = {"Authorization": f"Bearer {api_key}"}
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    async with httpx.AsyncClient(timeout=timeout) as client:
        upload_resp = await client.post(
            f"{base_url.rstrip('/')}/files",
            headers=headers,
            data={"purpose": "file-extract"},
            files={"file": (filename, data, mime)},
        )
        upload_resp.raise_for_status()
        file_obj = upload_resp.json()
        file_id = file_obj["id"]
        try:
            content_resp = await client.get(
                f"{base_url.rstrip('/')}/files/{file_id}/content",
                headers=headers,
            )
            content_resp.raise_for_status()
            payload = content_resp.json()
            text = payload.get("content", "")
            return str(text)[:MAX_EXTRACTED_CHARS]
        finally:
            # 解析完成后主动清理云端临时文件，节省用户存储配额
            try:
                await client.delete(f"{base_url.rstrip('/')}/files/{file_id}", headers=headers)
            except Exception:
                pass


def process_uploaded_image(filename: str, data: bytes) -> dict[str, Any]:
    """压缩规范化上传/截屏图片并返回可发送给视觉模型的元数据."""
    img = Image.open(io.BytesIO(data))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    max_side = 1920
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    fmt = "PNG" if img.mode == "RGBA" else "JPEG"
    save_kwargs = {"optimize": True} if fmt == "PNG" else {"quality": 88, "optimize": True}
    img.save(out, format=fmt, **save_kwargs)
    encoded_bytes = out.getvalue()

    file_id = uuid.uuid4().hex[:12]
    ext = ".png" if fmt == "PNG" else ".jpg"
    saved_path = get_uploads_dir() / f"{file_id}{ext}"
    saved_path.write_bytes(encoded_bytes)

    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    data_url = f"data:{mime};base64,{base64.b64encode(encoded_bytes).decode('ascii')}"
    return {
        "id": file_id,
        "kind": "image",
        "name": filename,
        "mime": mime,
        "size": len(encoded_bytes),
        "width": img.size[0],
        "height": img.size[1],
        "local_path": str(saved_path),
        "data_url": data_url,
    }


async def process_uploaded_file(
    filename: str,
    data: bytes,
    provider: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """统一入口：自动区分图片与文档，Kimi 优先走官方 Files API，失败或非 Kimi 自动本地解析."""
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTS:
        return process_uploaded_image(filename, data)

    file_id = uuid.uuid4().hex[:12]
    extracted_text = ""
    parse_mode = "local"

    if (
        provider
        and provider.get("supports_files_api")
        and provider.get("api_key")
        and provider.get("base_url")
    ):
        try:
            extracted_text = await extract_document_via_kimi(
                base_url=provider["base_url"],
                api_key=provider["api_key"],
                filename=filename,
                data=data,
            )
            parse_mode = "kimi_files_api"
        except Exception:
            extracted_text = ""

    if not extracted_text:
        extracted_text = extract_document_local(filename, data)
        parse_mode = "local"

    saved_path = get_uploads_dir() / f"{file_id}.txt"
    saved_path.write_text(extracted_text, encoding="utf-8")

    return {
        "id": file_id,
        "kind": "document",
        "name": filename,
        "size": len(data),
        "chars": len(extracted_text),
        "parse_mode": parse_mode,
        "text_path": str(saved_path),
        "preview": extracted_text[:200],
    }


def load_attachment_text(attachment: dict[str, Any]) -> str:
    text_path = attachment.get("text_path")
    if text_path and Path(text_path).exists():
        return Path(text_path).read_text(encoding="utf-8", errors="ignore")
    return attachment.get("preview", "")


def load_image_data_url(attachment: dict[str, Any]) -> str:
    if attachment.get("data_url"):
        return attachment["data_url"]
    local_path = attachment.get("local_path")
    if local_path and Path(local_path).exists():
        mime = attachment.get("mime", "image/png")
        b64 = base64.b64encode(Path(local_path).read_bytes()).decode("ascii")
        return f"data:{mime};base64,{b64}"
    return ""
