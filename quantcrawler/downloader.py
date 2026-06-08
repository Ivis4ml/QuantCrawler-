"""PDF 下载器：限速下载、PDF 校验、sha256、断点续传。"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from .http import HttpClient

log = logging.getLogger("quantcrawler.downloader")


def doi_slug(doi: str | None, openalex_id: str) -> str:
    """从 DOI（或 OpenAlex id）生成文件系统安全的文件名片段。"""
    base = doi or openalex_id
    base = base.rsplit("/", 1)[-1] if base.startswith("http") else base
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if base.lower().startswith(prefix):
            base = base[len(prefix):]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")
    return slug or "paper"


def target_path(pdf_dir: Path, journal_slug: str, year: int | None,
                doi: str | None, openalex_id: str) -> Path:
    y = str(year) if year else "unknown"
    return pdf_dir / journal_slug / y / f"{doi_slug(doi, openalex_id)}.pdf"


def _looks_like_pdf(content: bytes) -> bool:
    # PDF 以 %PDF- 开头（允许前置少量 BOM / 空白）。
    head = content[:1024].lstrip()
    return head.startswith(b"%PDF-")


class DownloadResult:
    __slots__ = ("ok", "path", "sha256", "status", "error")

    def __init__(self, ok: bool, path: str | None, sha256: str | None,
                 status: str, error: str | None):
        self.ok = ok
        self.path = path
        self.sha256 = sha256
        self.status = status
        self.error = error


_PDF_ACCEPT = "application/pdf,application/octet-stream,*/*"


class Downloader:
    def __init__(self, http: HttpClient, pdf_dir: Path,
                 min_pdf_bytes: int = 8192, max_pdf_bytes: int = 50 * 1024 * 1024):
        self.http = http
        self.pdf_dir = pdf_dir
        self.min_pdf_bytes = min_pdf_bytes
        self.max_pdf_bytes = max_pdf_bytes

    def download(self, url: str, dest: Path) -> DownloadResult:
        if dest.exists() and dest.stat().st_size >= self.min_pdf_bytes:
            return DownloadResult(True, str(dest), _sha256_file(dest), "downloaded", None)

        dest.parent.mkdir(parents=True, exist_ok=True)
        # 临时文件名按目标路径派生，并发下不同论文不冲突。
        tmp = dest.with_name(dest.name + ".part")
        hasher = hashlib.sha256()

        class _Sink:
            def __init__(self, fh):
                self.fh = fh
            def write(self, b):
                hasher.update(b)
                self.fh.write(b)

        try:
            with open(tmp, "wb") as fh:
                ok, n, err = self.http.stream_to_file(
                    url, _Sink(fh), max_bytes=self.max_pdf_bytes,
                    headers={"Accept": _PDF_ACCEPT},
                    first_chunk_validator=_looks_like_pdf,
                )
        except OSError as exc:
            _safe_unlink(tmp)
            return DownloadResult(False, None, None, "failed", f"写入失败 {exc}")

        if not ok:
            _safe_unlink(tmp)
            # 内容不是 PDF（多为付费墙落地页 HTML）-> paywalled；其余按失败处理。
            status = "paywalled" if err == "non-pdf-content" else "failed"
            return DownloadResult(False, None, None, status, err)
        if n < self.min_pdf_bytes:
            _safe_unlink(tmp)
            return DownloadResult(False, None, None, "failed", f"PDF 过小 {n}B")

        tmp.replace(dest)
        return DownloadResult(True, str(dest), hasher.hexdigest(), "downloaded", None)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
