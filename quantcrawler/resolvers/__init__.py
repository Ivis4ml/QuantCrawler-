"""PDF 来源解析器。

每个解析器尝试为一篇论文找到一个合法的开放获取 PDF 直链，返回
(source_label, pdf_url) 或 None。解析器按优先级依次尝试：

1. OpenAlex 自带 OA 位置（采集阶段已写入，无需再次请求）；
2. Unpaywall（按 DOI）；
3. arXiv（按标题 / DOI 匹配，限 q-fin / stat / econ）。
"""

from .unpaywall import resolve_unpaywall, best_oa
from .arxiv import resolve_arxiv
from .semantic_scholar import resolve_semantic_scholar
from .openaire import resolve_openaire

__all__ = ["resolve_unpaywall", "resolve_arxiv", "resolve_semantic_scholar",
           "resolve_openaire", "resolve_candidates"]


def resolve_candidates(http, doi, title, mailto):
    """汇总各来源的开放获取候选，返回去重后的 [(source, url), ...]。

    顺序：Unpaywall -> Semantic Scholar -> arXiv（标题搜索，最慢）。
    arXiv 标题搜索仅在前面都没拿到真正的 PDF 直链时才跑，既省请求又降误匹配；
    Semantic Scholar 常直接给出 arXiv / 机构库 / PMC 直链，能补回不少 OA。
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(cand):
        if cand and cand[1] not in seen:
            seen.add(cand[1])
            out.append(cand)

    up = best_oa(http, doi, mailto)          # (url, is_direct_pdf) | None
    if up:
        add(("unpaywall", up[0]))
    s2 = resolve_semantic_scholar(http, doi)
    add(s2)
    oair = resolve_openaire(http, doi)       # 仓库 / 工作论文 .pdf 直链
    add(oair)

    have_direct = (up and up[1]) or bool(s2) or bool(oair)
    if not have_direct:                       # 仅在都没拿到直链时才做最慢的 arXiv 标题搜索
        add(resolve_arxiv(http, title))
    return out
