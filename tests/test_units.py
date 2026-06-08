"""核心纯逻辑单元测试（不依赖网络）。运行：python -m pytest tests/ 或 python tests/test_units.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantcrawler.openalex import reconstruct_abstract, pdf_urls_from_work
from quantcrawler.relevance import RelevanceFilter
from quantcrawler.downloader import doi_slug, _looks_like_pdf
from quantcrawler.resolvers.arxiv import _similar, _normalize_title
from quantcrawler.resolvers.unpaywall import _normalize_doi


def test_reconstruct_abstract():
    inv = {"We": [0], "study": [1], "markets": [2]}
    assert reconstruct_abstract(inv) == "We study markets"
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


_CFG = {
    "finance_topics": ["Volatility", "Asset Pricing"],
    "finance_keywords": ["high-frequency", "volatility", "crypto", "asset pricing"],
    "general_topics": ["Machine Learning"],
    "general_keywords": ["high-dimensional", "machine learning", "neural network"],
    "exclude_topics": ["Corporate Finance and Governance", "Banking"],
}


def test_relevance_include_all():
    rf = RelevanceFilter(_CFG)
    ok, reason = rf.evaluate(include_all=True, category="core_finance", title="Anything",
                             abstract=None, primary_topic=None, topics=[])
    assert ok and reason == "include_all:journal"


def test_relevance_finance_keyword():
    rf = RelevanceFilter(_CFG)
    ok, reason = rf.evaluate(include_all=False, category="core_finance",
                             title="A study of High-Frequency trading",
                             abstract=None, primary_topic=None, topics=[])
    assert ok and reason == "finance-kw:high-frequency"

    ok2, _ = rf.evaluate(include_all=False, category="core_finance",
                         title="Corporate governance reform",
                         abstract="board independence", primary_topic="Governance", topics=[])
    assert not ok2


def test_relevance_finance_topic():
    rf = RelevanceFilter(_CFG)
    ok, reason = rf.evaluate(include_all=False, category="core_finance", title="Some paper",
                             abstract=None, primary_topic="Market Dynamics and Volatility", topics=[])
    assert ok and reason == "finance-topic:volatility"


def test_relevance_word_boundary():
    rf = RelevanceFilter(_CFG)
    ok, _ = rf.evaluate(include_all=False, category="core_finance",
                        title="Advances in cryptography systems",
                        abstract=None, primary_topic=None, topics=[])
    assert not ok
    ok2, _ = rf.evaluate(include_all=False, category="core_finance",
                         title="Pricing crypto assets",
                         abstract=None, primary_topic=None, topics=[])
    assert ok2


def test_relevance_category_gate():
    """非金融本位刊：通用方法词不单独成立，必须有金融信号。"""
    rf = RelevanceFilter(_CFG)
    # 通用 ML 论文：金融刊纳入，非金融刊排除
    ml_title = "High-Dimensional Transfer Learning with Neural Network methods"
    ok_fin, reason_fin = rf.evaluate(include_all=False, category="microstructure_quant",
                                     title=ml_title, abstract=None, primary_topic=None, topics=[])
    assert ok_fin and reason_fin.startswith("general-")
    ok_stat, reason_stat = rf.evaluate(include_all=False, category="management_stats",
                                       title=ml_title, abstract=None, primary_topic=None, topics=[])
    assert not ok_stat and reason_stat == "no-finance-signal"
    # 带金融信号的统计论文：非金融刊也纳入
    ok2, reason2 = rf.evaluate(include_all=False, category="management_stats",
                               title="High-Dimensional estimation of realized volatility",
                               abstract=None, primary_topic=None, topics=[])
    assert ok2 and reason2 == "finance-kw:volatility"


def test_doi_slug():
    assert doi_slug("https://doi.org/10.1093/jjfinec/nbaa013", "x") == "nbaa013"
    assert doi_slug(None, "https://openalex.org/W123") == "W123"


def test_looks_like_pdf():
    assert _looks_like_pdf(b"%PDF-1.5\n...")
    assert _looks_like_pdf(b"  \n%PDF-1.4")
    assert not _looks_like_pdf(b"<!DOCTYPE html>")


def test_title_similarity():
    a = _normalize_title("Deep Learning for Mortgage Risk")
    b = _normalize_title("Deep learning for mortgage risk!")
    assert _similar(a, b) == 1.0
    c = _normalize_title("A completely different paper title")
    assert _similar(a, c) < 0.3


def test_normalize_doi():
    assert _normalize_doi("https://doi.org/10.1/x") == "10.1/x"
    assert _normalize_doi("doi:10.2/y") == "10.2/y"
    assert _normalize_doi("") is None


def test_pdf_urls_from_work():
    work = {
        "best_oa_location": {"pdf_url": "https://a/x.pdf"},
        "primary_location": {"pdf_url": None},
        "locations": [{"pdf_url": "https://b/y.pdf"}, {"pdf_url": "https://a/x.pdf"}],
        "open_access": {"oa_url": "https://c/z"},
    }
    urls = pdf_urls_from_work(work)
    assert urls == ["https://a/x.pdf", "https://b/y.pdf", "https://c/z"]


def test_relevance_exclude_topic():
    """primary_topic 属公司金融 / 银行等排除方向时，仅靠主题信号不纳入；
    但金融专用关键词仍可放行（强信号）。"""
    rf = RelevanceFilter(_CFG)
    # 仅通过金融主题命中，但 primary_topic 是公司金融 -> 排除
    ok, reason = rf.evaluate(include_all=False, category="core_finance",
                             title="Corporate payout policy", abstract="dividends",
                             primary_topic="Corporate Finance and Governance",
                             topics=["Asset Pricing"])
    assert not ok and reason.startswith("excluded-topic:"), reason
    # 同样 primary_topic，但命中金融关键词（high-frequency）-> 仍纳入
    ok2, reason2 = rf.evaluate(include_all=False, category="core_finance",
                               title="High-Frequency trading around payouts", abstract=None,
                               primary_topic="Corporate Finance and Governance", topics=[])
    assert ok2 and reason2 == "finance-kw:high-frequency", reason2


def test_select_top_per_year(tmp_path=None):
    import tempfile, os
    from quantcrawler.db import Catalog
    from quantcrawler.models import Paper
    d = tempfile.mkdtemp()
    db = os.path.join(d, "t.sqlite")
    c = Catalog(db)
    papers = []
    # journal A, year 2020: 5 quant papers with cites 10,9,8,7,6 + 1 non-quant cites 100
    for i, cites in enumerate([10, 9, 8, 7, 6]):
        papers.append(Paper(openalex_id=f"A20-{i}", journal_slug="A", journal_name="A",
                            publication_year=2020, cited_by_count=cites, is_quant=True))
    papers.append(Paper(openalex_id="A20-nq", journal_slug="A", journal_name="A",
                        publication_year=2020, cited_by_count=100, is_quant=False))
    # journal A, year 2021: 2 quant papers (under quota)
    for i, cites in enumerate([3, 5]):
        papers.append(Paper(openalex_id=f"A21-{i}", journal_slug="A", journal_name="A",
                            publication_year=2021, cited_by_count=cites, is_quant=True))
    c.upsert_papers(papers)

    stats = c.select_top_per_year(top_per_year=3, since_year=2020, until_year=2021)
    # eligible = 7 quant in range; selected = 3 (A2020 top3) + 2 (A2021 all) = 5
    assert stats["eligible"] == 7, stats
    assert stats["selected"] == 5, stats
    # non-quant must never be selected even with huge citations
    nq = c.conn.execute("SELECT selected FROM papers WHERE openalex_id='A20-nq'").fetchone()[0]
    assert nq == 0
    # the top-3 of 2020 must be cites 10,9,8 (ids 0,1,2); 7,6 excluded
    sel2020 = {r[0] for r in c.conn.execute(
        "SELECT openalex_id FROM papers WHERE publication_year=2020 AND selected=1")}
    assert sel2020 == {"A20-0", "A20-1", "A20-2"}, sel2020
    # 2021 both selected (under quota)
    sel2021 = c.conn.execute(
        "SELECT SUM(selected) FROM papers WHERE publication_year=2021").fetchone()[0]
    assert sel2021 == 2
    # idempotent: re-run with smaller N reshapes correctly
    stats2 = c.select_top_per_year(top_per_year=1, since_year=2020, until_year=2021)
    assert stats2["selected"] == 2  # 1 per (A,2020) + 1 per (A,2021)
    c.close()


def test_retry_after_parse():
    from quantcrawler.http import HttpClient
    assert HttpClient._parse_retry_after("3") == 3.0
    assert HttpClient._parse_retry_after("abc") is None
    # HTTP-date 形式不应抛异常，返回非负秒数（过去时间 -> 0）
    v = HttpClient._parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT")
    assert v is not None and v >= 0.0


def test_host_rate_limiter_spacing():
    from quantcrawler.http import HostRateLimiter
    import time
    rl = HostRateLimiter(default_rps=1000, host_rps={"slow.example": 5})  # 0.2s 间隔
    rl.wait("https://slow.example/a")
    t0 = time.monotonic()
    rl.wait("https://slow.example/b")  # 同主机，应至少等 ~0.2s
    assert time.monotonic() - t0 >= 0.15
    # 不同主机不受该桶约束
    t1 = time.monotonic()
    rl.wait("https://fast.example/x")
    assert time.monotonic() - t1 < 0.1


def test_migration_old_db():
    import tempfile, os, sqlite3
    from quantcrawler.db import Catalog
    d = tempfile.mkdtemp()
    db = os.path.join(d, "old.sqlite")
    # 造一个只有核心列的旧库
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE papers (openalex_id TEXT PRIMARY KEY, title TEXT)")
    conn.commit(); conn.close()
    c = Catalog(db)  # 应自动补列且不报错
    cols = {r[1] for r in c.conn.execute("PRAGMA table_info(papers)").fetchall()}
    for need in ("cited_by_count", "selected", "pdf_url", "download_status", "harvested_at"):
        assert need in cols, need
    c.close()


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
