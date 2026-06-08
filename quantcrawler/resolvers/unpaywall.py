"""Unpaywall 解析器：按 DOI 查询开放获取 PDF。"""

from __future__ import annotations

import logging
from typing import Any

from ..http import HttpClient

log = logging.getLogger("quantcrawler.resolvers.unpaywall")

BASE = "https://api.unpaywall.org/v2"


def _normalize_doi(doi: str) -> str | None:
    if not doi:
        return None
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
    return doi or None


def best_oa(http: HttpClient, doi: str | None, mailto: str) -> tuple[str, bool] | None:
    """返回 (url, is_direct_pdf)。优先在 best_oa_location 与全部 oa_locations 中寻找
    真正的 PDF 直链（url_for_pdf）；全部为空才回退到落地页 url（is_direct_pdf=False）。
    出版社的落地页常被下载器判为非 PDF，故区分两者，便于上层决定是否再试 arXiv。"""
    norm = _normalize_doi(doi or "")
    if not norm:
        return None
    resp = http.get(f"{BASE}/{norm}", params={"email": mailto})
    if resp is None or resp.status_code != 200:
        return None
    data: dict[str, Any] = resp.json()
    if not data.get("is_oa"):
        return None
    locations = [data.get("best_oa_location") or {}, *(data.get("oa_locations") or [])]
    # 第一遍：找 PDF 直链
    for loc in locations:
        if loc.get("url_for_pdf"):
            return (loc["url_for_pdf"], True)
    # 第二遍：回退落地页
    for loc in locations:
        if loc.get("url"):
            return (loc["url"], False)
    return None


def resolve_unpaywall(http: HttpClient, doi: str | None, mailto: str) -> tuple[str, str] | None:
    r = best_oa(http, doi, mailto)
    return ("unpaywall", r[0]) if r else None
