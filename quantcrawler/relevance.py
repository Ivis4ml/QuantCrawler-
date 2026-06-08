"""量化相关性筛选，按期刊类别区分口径。

信号分两组：
- 金融信号（finance_topics / finance_keywords）：金融专用，对所有期刊都算数。
- 通用方法信号（general_topics / general_keywords）：统计 / 机器学习 / 运筹等通用
  方法词，仅对金融本位刊算数。

判定：
1. 期刊 include_all=True -> 直接纳入。
2. 非金融本位刊（category=management_stats，如 JASA / Management Science / Operations
   Research / Econometrica / J.Econometrics / JBES）：必须命中金融信号。这样可避免把
   这些刊里高引用的通用统计 / ML / OR 论文误纳（它们会被 select 按引用顶上来）。
3. 金融本位刊：命中金融信号或通用方法信号之一即可（宽口径）。

返回 (is_quant, reason)。reason 记录命中依据，便于事后审查与调参。
"""

from __future__ import annotations

import re
from typing import Any

NON_FINANCE_CATEGORY = "management_stats"


def _compile_keywords(words: list[str]) -> list[tuple[str, re.Pattern]]:
    return [
        (w, re.compile(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])"))
        for w in (k.lower() for k in words)
    ]


class RelevanceFilter:
    def __init__(self, relevance_cfg: dict[str, Any]):
        self.finance_topics = [s.lower() for s in relevance_cfg.get("finance_topics", [])]
        self.general_topics = [s.lower() for s in relevance_cfg.get("general_topics", [])]
        self.exclude_topics = [s.lower() for s in relevance_cfg.get("exclude_topics", [])]
        self.finance_kw = _compile_keywords(relevance_cfg.get("finance_keywords", []))
        self.general_kw = _compile_keywords(relevance_cfg.get("general_keywords", []))

    @staticmethod
    def _match_topic(subs: list[str], topic_blob: str) -> str | None:
        for sub in subs:
            if sub in topic_blob:
                return sub
        return None

    @staticmethod
    def _match_keyword(patterns: list[tuple[str, re.Pattern]], text: str) -> str | None:
        for kw, pat in patterns:
            if pat.search(text):
                return kw
        return None

    def evaluate(
        self,
        *,
        include_all: bool,
        category: str,
        title: str | None,
        abstract: str | None,
        primary_topic: str | None,
        topics: list[str],
    ) -> tuple[bool, str]:
        if include_all:
            return True, "include_all:journal"

        topic_blob = " ".join(filter(None, [primary_topic, *topics])).lower()
        text = " ".join(filter(None, [title, abstract])).lower()

        # 金融关键词（标题 / 摘要）：金融专用强信号，对所有期刊都算数，且不受排除主题影响。
        fk = self._match_keyword(self.finance_kw, text) if text else None
        if fk:
            return True, f"finance-kw:{fk}"

        # 非金融本位刊到此为止：不采用金融主题信号。OpenAlex 会给通用时间序列 / 极值
        # / 统计方法论文过度赋上金融类主题（如 Volatility），故主题在这些刊不可靠。
        if category == NON_FINANCE_CATEGORY:
            return False, "no-finance-signal"

        # 排除主题：primary_topic 命中非二级市场方向（公司金融 / 银行 / 宏观等）时，
        # 仅靠主题 / 通用信号不足以纳入（已被上面的金融关键词放行的不会走到这里）。
        excluded = self._match_topic(self.exclude_topics, (primary_topic or "").lower())

        # 金融本位刊：金融主题 + 通用方法信号都算数（宽口径），但受排除主题约束。
        ft = self._match_topic(self.finance_topics, topic_blob)
        gt = self._match_topic(self.general_topics, topic_blob)
        gk = self._match_keyword(self.general_kw, text) if text else None
        if ft or gt or gk:
            if excluded:
                return False, f"excluded-topic:{excluded}"
            if ft:
                return True, f"finance-topic:{ft}"
            if gt:
                return True, f"general-topic:{gt}"
            return True, f"general-kw:{gk}"

        return False, "no-match"
