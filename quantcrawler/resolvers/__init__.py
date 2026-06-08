"""PDF 来源解析器。

每个解析器尝试为一篇论文找到一个合法的开放获取 PDF 直链，返回
(source_label, pdf_url) 或 None。解析器按优先级依次尝试：

1. OpenAlex 自带 OA 位置（采集阶段已写入，无需再次请求）；
2. Unpaywall（按 DOI）；
3. arXiv（按标题 / DOI 匹配，限 q-fin / stat / econ）。
"""

from .unpaywall import resolve_unpaywall, best_oa
from .arxiv import resolve_arxiv

__all__ = ["resolve_unpaywall", "resolve_arxiv", "resolve_candidates"]


def resolve_candidates(http, doi, title, mailto):
    """汇总各来源的开放获取候选，返回去重后的 [(source, url), ...]。

    Unpaywall 先行：若返回真正的 PDF 直链（url_for_pdf），则跳过 arXiv 网络请求以
    减少对受限速的 arXiv 的访问；否则（Unpaywall 仅有落地页，可能是被拦截的出版社
    直链）仍尝试 arXiv 作为兜底。
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(cand):
        if cand and cand[1] not in seen:
            seen.add(cand[1])
            out.append(cand)

    up = best_oa(http, doi, mailto)
    if up:
        add(("unpaywall", up[0]))
    if not (up and up[1]):  # up[1] = is_direct_pdf；非直链或无结果才试 arXiv
        add(resolve_arxiv(http, title))
    return out
