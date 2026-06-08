# AGENTS.md（中文版）

面向 AI 编码 agent（Codex、Cursor、Claude Code 等）的项目说明。改动需遵守下述约定。
完整设计见 `CLAUDE.md`；本文件是简明、跨工具的速查。英文版：`AGENTS.md`（各工具默认
加载的是英文版）。

## agent 如何加载本文件

- **OpenAI Codex（CLI / 云端）**：自动读取仓库根目录的 `AGENTS.md`。在本目录直接运行
  `codex`（或 `codex "你的任务"`）即可。Codex 还会合并全局 `~/.codex/AGENTS.md` 与子目录
  下更具体的 `AGENTS.md`（越具体优先级越高）。模型、审批策略、沙箱等全局配置放在
  `~/.codex/config.toml`，不放这里。把本文件放在根目录就够了，无需额外接线。
- **Cursor / Windsurf / Aider / Jules 等**：同样自动读取根目录的 `AGENTS.md`。
- **Claude Code**：读取 `CLAUDE.md`（更详细、权威的设计文档）。改动项目事实时，请保持
  `AGENTS.md`、`AGENTS.zh.md` 与 `CLAUDE.md` 一致。

## 项目是什么

**QuantCrawler** —— 一个爬虫，从 20+ 本金融与量化顶刊中，采集 2020–2026 年发表、且与
**二级市场、市场微观结构、高频交易、量化因子**相关的论文，在 SQLite 中记录完整元数据，
并在存在合法开放获取副本时下载原文 PDF。单一用途的 Python 命令行工具，无 Web 服务、无框架。

## 硬约束（不可违反）

- **仅开放获取**：只下载合法开放副本（出版社 OA、arXiv、经 OpenAlex / Unpaywall 收录的
  SSRN / NBER / RePEc 预印本）。付费墙论文只记元数据与 DOI。**绝不绕过、不破解付费墙 /
  Cloudflare**。403 记为 `failed`，不做规避。
- **做礼貌的 API 使用者**：所有 OpenAlex / Unpaywall / Crossref 请求携带
  `config/settings.yaml` 里的 `mailto`。按主机限速是强制的，arXiv 固定约 1 rps。提高并发
  时必须保持按主机配额。
- **幂等且可续跑**：每个阶段都能安全重跑；进度在 SQLite，重跑只处理未完成行。编辑时保持
  这一性质。

## 安装与运行

```bash
pip install -r requirements.txt          # 依赖：httpx, pyyaml（其余标准库）
python --version                         # 开发于 3.13；需 3.11+

# 流水线（每个阶段幂等 / 可续跑）：
python -m quantcrawler resolve-sources   # ISSN -> OpenAlex Source ID（缓存入库）
python -m quantcrawler harvest           # 枚举 works、重建摘要、记引用数、相关性筛选
python -m quantcrawler select            # 每刊每年按引用取前 N（可选封顶）
python -m quantcrawler resolve-pdfs      # 经 Unpaywall + arXiv 定位 OA（并发）
python -m quantcrawler download          # 并发流式下载到 data/pdfs/
python -m quantcrawler report            # 输出 paper_list.csv、download_worklist.csv、summary.md
python -m quantcrawler reconcile         # 把磁盘已有 PDF 标记为 downloaded（私下交接 PDF 用）
python -m quantcrawler import-pdf --doi DOI --file PATH   # 把手动下载的一个 PDF 按 DOI 归位

python -m quantcrawler run               # 顺序执行以上全部
python -m quantcrawler stats             # 打印库内统计

# 常用参数：
#   --journal SLUG     仅处理单刊（slug 见 config/journals.yaml）
#   --config DIR --data DIR   覆盖配置 / 数据目录
#   download --limit N --retry-failed
#   -v                 调试日志（放在子命令之前）

python tests/test_units.py               # 单元测试（不联网）；当前 16/16 通过
```

## 仓库结构

```
config/
  journals.yaml          21 本期刊：slug、name、issn、category、include_all、source_id、metadata_source
  settings.yaml          mailto、采集窗口 since/until、主题词表（finance/general/exclude 关键词+主题）、
                         http 与 download（限速、worker 数、max_pdf_bytes）、download_scope、top_per_year
quantcrawler/
  __main__.py / cli.py   argparse 命令行入口（python -m quantcrawler ...）
  config.py              load_settings()；Settings 与 Journal dataclass
  models.py              Paper dataclass（papers 表一行）
  db.py                  SQLite Catalog：建表、内省式迁移、upsert、select_top_per_year、counts
  http.py                HttpClient + HostRateLimiter（线程安全、按主机）；重试退避；stream_to_file
  openalex.py            source 解析、works 游标分页、摘要重建、pdf 候选
  crossref.py            OpenAlex 收录不佳的期刊（Review of Finance）的 Crossref 采集通路
  relevance.py           RelevanceFilter —— 按类别区分的量化相关性判定
  downloader.py          流式 PDF 下载、%PDF 校验、体积上限、sha256、原子写入
  pipeline.py            各阶段编排（resolve-sources/harvest/select/resolve-pdfs/download/report）
  resolvers/
    __init__.py          resolve_candidates() —— 汇总 Unpaywall + arXiv
    unpaywall.py         best_oa() 优先 url_for_pdf 而非落地页
    arxiv.py             按标题匹配 arXiv（q-fin/stat/econ），返回 pdf 链接
tests/test_units.py      纯逻辑单元测试（相关性、select、http 解析、迁移等）
data/                    运行时产物：catalog.sqlite、pdfs/<期刊>/<年>/<doi>.pdf、reports/
CLAUDE.md                完整设计文档 + 计划（权威）
Journals.md              21 本期刊及简介
warmup_brief.html        实习生上手页面
```

## 一段话架构

两条元数据通路汇入一个 SQLite catalog：**OpenAlex**（默认，按 Source ID + 日期窗口）与
**Crossref**（`metadata_source: crossref` 的期刊兜底）。`harvest` 用 `RelevanceFilter`
判定每篇，存 `is_quant`、`relevance_reason`、`cited_by_count` 与 OpenAlex OA 链接。
`select` 可按引用对每个（期刊, 年份）取前 N。`resolve-pdfs` 经 **Unpaywall** 再 **arXiv**
补 OA 链接（并发，arXiv 限速）。`download` 并发流式下载到 `data/pdfs/`，校验 `%PDF` 魔数、
算 sha256。`report` 输出完整清单、未下载的失败清单与汇总。

## 相关性筛选（最易踩坑处）

`RelevanceFilter.evaluate(include_all, category, title, abstract, primary_topic, topics)`：
- `include_all: true` 的纯量化刊（如 Quantitative Finance）→ 全收。
- **金融关键词**命中 → 对任何期刊都纳入（强信号）。
- `category == "management_stats"`（JASA、MS、OR、Econometrica、J. Econometrics、JBES）
  → **到此为止**，只认金融关键词。避免误收会被引用数顶上来的通用统计 / ML / OR 论文。
- 金融本位刊 → 金融主题 + 通用方法主题/关键词也算数。
- `exclude_topics` 剔除 primary_topic 属公司金融 / 银行 / 宏观 / 家庭金融等的论文（除非已被
  金融关键词命中）。

词表在 `config/settings.yaml`（`finance_keywords`、`general_keywords`、`finance_topics`、
`general_topics`、`exclude_topics`）。调词表，别改代码。

## 数据模型（papers 表）

列的单一事实来源是 `db.py` 的 `_PAPERS_COLUMNS`（同时驱动 CREATE TABLE 与旧库自动迁移）。
关键字段：`openalex_id`（主键）、`doi`、`title`、`authors`(JSON)、`journal_slug`、
`publication_year`、`abstract`、`primary_topic`、`topics`(JSON)、`cited_by_count`、
`is_quant`、`relevance_reason`、`selected`、`pdf_source`(openalex/unpaywall/arxiv/none)、
`pdf_url`、`pdf_landing`、`pdf_path`、`sha256`、`download_status`
(pending/downloaded/paywalled/failed)、`error`。

加列：追加到 `_PAPERS_COLUMNS` 即自动迁移。JSON 列要登记进 `_JSON_FIELDS`。重采时不可被
覆盖的字段（下载结果、`selected`）在 `upsert_papers` 的 `preserve` 集合里。

## 约定

- Python 3.11+，标准库优先。第三方依赖只有 `httpx`、`pyyaml`。无充分理由不加依赖。
- 并发用 `concurrent.futures.ThreadPoolExecutor`；**工作线程只做网络/文件 IO，所有 SQLite
  写入在主线程**（sqlite 连接非线程安全）。保持这一分工。
- 代码与注释不使用 emoji。常规标点，不用 em dash。
- 注释用中文、代码标识符用英文；编辑某文件时与其周边风格一致。
- 新增纯逻辑请在 `tests/test_units.py` 加单测；测试不得联网。

## 两机交接

PDF 与 `catalog.sqlite` 已被 gitignore（版权原因：可读 ≠ 可再分发）。私下传输，不经公开
仓库。接手者把 `data/pdfs/` + `data/catalog.sqlite` 放进自己的克隆即可续跑——已下载的会被
跳过（`downloaded` 不会再被选；下载器也会在目标文件已存在时跳过）。若只拿到 PDF（无库），
先 `harvest` 再 `reconcile`。详见 `HANDOFF.md`。

## 当前状态（快照）

- 已配置 21 本期刊；窗口 2020–2026；`download_scope: all`。
- 采集完成：库内 **4,590** 篇相关论文（`paper_list.csv`）。
- 下载进行中；免费 OA 命中率约 10–20%（出版社直链多被 Cloudflare 拦截 → 记为
  `failed`/`paywalled`）。其余需机构/校园网访问，清单见 `download_worklist.csv`。
- 单元测试：16/16 通过。

## 待办（尚未实现）

见 `CLAUDE.md` 末尾清单。重点：持久化全部 OpenAlex OA 候选（`pdf_candidates` 列）以补全
回退链；arXiv 基于 DOI 的匹配 + 放宽标题阈值；关键词复数/屈折召回；Paper Digest 种子语料
连接器（`seeds/paperdigest.py`）。
