"""arXiv 解析器：按标题在 arXiv 检索预印本，匹配后返回 PDF 直链。

仅接受 q-fin / stat / econ / math.* 相关分类，并要求标题高度相似，避免误匹配。
arXiv API 返回 Atom XML，用标准库 xml.etree 解析。
"""

from __future__ import annotations

import logging
import re
from xml.etree import ElementTree as ET

from ..http import HttpClient

log = logging.getLogger("quantcrawler.resolvers.arxiv")

API = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"

_ACCEPT_PREFIXES = ("q-fin", "stat", "econ", "math", "cs.lg", "cs.ce")


def _normalize_title(t: str) -> str:
    t = t.lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _similar(a: str, b: str) -> float:
    """归一化标题的 token Jaccard 相似度。"""
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def resolve_arxiv(
    http: HttpClient, title: str | None, threshold: float = 0.85,
) -> tuple[str, str] | None:
    if not title or len(title) < 8:
        return None
    norm_target = _normalize_title(title)
    query = f'ti:"{title}"'
    resp = http.get(API, params={"search_query": query, "max_results": 5})
    if resp is None or resp.status_code != 200:
        return None
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return None

    for entry in root.findall(f"{_ATOM}entry"):
        etitle_el = entry.find(f"{_ATOM}title")
        if etitle_el is None or not etitle_el.text:
            continue
        if _similar(norm_target, _normalize_title(etitle_el.text)) < threshold:
            continue
        if not _category_accepted(entry):
            continue
        pdf = _pdf_link(entry)
        if pdf:
            return ("arxiv", pdf)
    return None


def _category_accepted(entry: ET.Element) -> bool:
    terms: list[str] = []
    prim = entry.find(f"{_ARXIV}primary_category")
    if prim is not None and prim.get("term"):
        terms.append(prim.get("term", ""))
    for cat in entry.findall(f"{_ATOM}category"):
        if cat.get("term"):
            terms.append(cat.get("term", ""))
    for t in terms:
        tl = t.lower()
        if any(tl.startswith(p) for p in _ACCEPT_PREFIXES):
            return True
    return False


def _pdf_link(entry: ET.Element) -> str | None:
    for link in entry.findall(f"{_ATOM}link"):
        if link.get("title") == "pdf" or link.get("type") == "application/pdf":
            href = link.get("href")
            if href:
                return href
    # 兜底：用 abs id 推导 pdf 链接
    idel = entry.find(f"{_ATOM}id")
    if idel is not None and idel.text and "/abs/" in idel.text:
        return idel.text.replace("/abs/", "/pdf/")
    return None
