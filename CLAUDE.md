# QuantCrawler

金融顶刊量化论文采集器。枚举英文金融与量化顶刊 2020 年（含）至今的所有量化相关
论文，记录完整元数据，并在合法范围内下载开放获取（Open Access）原文 PDF。

本文件是项目的总体计划与开发说明。代码改动应与此处的设计保持一致；若设计变更，
请同步更新本文件。

## 1. 目标与范围

**采集 20 本英文金融与量化顶刊（见第 3 节）2020 年至今（2020-2026）中，与
二级市场、市场微观结构、高频交易、量化因子相关的论文，记录元数据并下载开放获取
原文 PDF。**

- 时间窗口：2020-01-01 至 2026-12-31（`settings.yaml` 的 `since` / `until`）。
- 主题：二级市场 / 微观结构 / 高频交易 / 量化因子（含相关资产定价、波动率、流动性、
  执行、组合）。排除公司金融、银行监管、家庭金融、房地产、宏观货币等非二级市场方向
  （见第 4 节 `exclude_topics`）。
- 采集范围：默认 `download_scope: all`，即全部相关论文都进入下载流程（不按篇数硬性
  封顶）。可选 `selected`，配合 `select` 阶段每刊每年按引用数取前 `top_per_year` 篇。

分层流程（hierarchical）：

1. 收集 20 本顶刊（见第 3 节）。
2. 枚举各刊 2020-2026 的论文，按主题筛出相关论文，记录引用数 -> 产出完整 **paper
   list**（`data/reports/paper_list.csv`）。
3. 对相关论文定位开放获取 PDF 并下载，持续统计下载 / 失败 / 付费墙状态。
4. 无法自动下载者汇总到 **失败清单**（`data/reports/download_worklist.csv`，含 DOI 与
   落地页），供校园网或人工下载。
5. 重跑各阶段均幂等续跑，统计随之更新。

`select` 阶段（可选）：在每个（期刊, 年份）单元内按引用数（`select_by: citations`，年内
排名以消除新论文的引用劣势）取前 `top_per_year` 篇，用于优先级排序或限量采集。

### 合规约束（重要）

本项目仅下载**合法的开放获取版本**，下载来源限于：

- 出版社开放获取 PDF（OpenAlex / Unpaywall 标注为 OA 的定稿版或作者版）；
- 预印本仓库：arXiv（q-fin / stat / econ）、SSRN、NBER、RePEc 等被 OpenAlex 或
  Unpaywall 收录为开放位置的副本。

对于仍处于付费墙后、无合法开放副本的论文：**只记录元数据与 DOI / 落地页链接，不
下载、不绕过付费墙**。项目不实现任何针对出版社的批量抓取、账号认证或付费墙绕过。

金融领域的特点：顶刊论文大多有 SSRN / NBER 工作论文版本，量化与计量方向多有
arXiv 预印本，因此开放获取版本的覆盖率在本领域相对较高。

## 2. 数据来源

| 用途 | 来源 | 接口 | 是否需密钥 |
|------|------|------|-----------|
| 期刊与论文元数据枚举 | OpenAlex | REST `api.openalex.org` | 否（polite pool 需 mailto） |
| 摘要 | OpenAlex `abstract_inverted_index` 重建 | — | 否 |
| 开放获取 PDF 定位（补充） | Unpaywall | `api.unpaywall.org/v2/{doi}` | 否（需 email 参数） |
| 开放获取 PDF 定位（补充） | Semantic Scholar | `api.semanticscholar.org/graph/v1`（openAccessPdf） | 否 |
| 开放获取 PDF 定位（补充） | OpenAIRE | `api.openaire.eu/search/publications` | 否 |
| 开放获取 PDF 定位（补充） | CORE | `api.core.ac.uk/v3/search/works`（downloadUrl） | 可选（`CORE_API_KEY` 环境变量提升配额，匿名亦可但限速严） |
| 预印本 PDF | arXiv | `export.arxiv.org/api/query`（Atom） | 否 |

选择 OpenAlex 为主源的理由：免费、无需密钥、覆盖全面、可按 source（期刊）与发表
日期过滤、自带开放获取位置与主题（topics）标注。Crossref 作为可选备用元数据源。

实测覆盖率（2020 年至今，抽样）：
- Journal of Financial Economics：874 篇文章，约 39% 有开放获取 PDF 链接，摘要重建
  率约 18%（Elsevier 限制 OpenAlex 摘要）。
- Quantitative Finance：695 篇文章，约 37% 有 PDF，摘要重建率约 95%。

补充 Unpaywall 与 arXiv 匹配后，开放获取命中率预期可进一步提升。

## 3. 期刊清单（20 本）

配置于 `config/journals.yaml`，可增删。`include_all: true` 表示该刊本质上即量化期
刊，全部论文纳入；否则按相关性筛选。`issn` 使用 ISSN-L。

**核心金融（综合顶刊，相关性筛选）**

1. The Journal of Finance — 0022-1082
2. Journal of Financial Economics — 0304-405X
3. The Review of Financial Studies — 0893-9454
4. Review of Finance — 1572-3097（注：OpenAlex 收录碎片化，需 Crossref 补采，
   或替换为 Journal of Financial Intermediation 1042-9573）

**微观结构 / 量化金融 / 数理金融**

5. Journal of Financial and Quantitative Analysis — 0022-1090
6. Journal of Financial Markets — 1386-4181（include_all）
7. Journal of Banking & Finance — 0378-4266
8. Journal of Empirical Finance — 0927-5398
9. Quantitative Finance — 1469-7688（include_all）
10. Mathematical Finance — 0960-1627（include_all）
11. Finance and Stochastics — 0949-2984（include_all，小刊，部分年份不足 20 篇）
12. SIAM Journal on Financial Mathematics — 1945-497X（include_all）
13. Journal of Financial Econometrics — 1479-8409（include_all）
14. The Review of Asset Pricing Studies — 2045-9920（小刊，约 21 篇/年）

**计量 / 统计 / 管理科学（相关性筛选）**

15. Journal of Econometrics — 0304-4076
16. Journal of the American Statistical Association — 0162-1459
17. Journal of Business & Economic Statistics — 0735-0015
18. Management Science — 0025-1909
19. Operations Research — 0030-364X
20. Econometrica — 0012-9682

各刊 OpenAlex Source ID 已在 `config/journals.yaml` 缓存（Review of Finance 除外，
其 OpenAlex 来源不完整）。

## 4. 量化相关性筛选（按期刊类别区分口径）

目标是「所有量化相关论文」。信号分两组（均在 `config/settings.yaml`）：

- **金融信号**：金融专用主题（`finance_topics`：金融市场、波动率、资产定价、衍生品、
  高频等）与金融专用关键词（`finance_keywords`：算法交易、市场微观结构、限价订单簿、
  最优执行、流动性、买卖价差、价格发现、波动率、GARCH、Value-at-Risk、资产定价、组
  合优化、统计套利、加密货币等）。
- **通用方法信号**：统计 / 机器学习 / 运筹等通用方法词（`general_topics` / `general_
  keywords`：时间序列、计量、机器学习、深度学习、强化学习、高维、非参数、因子模型、
  动量、Hawkes 过程等）。

判定规则：

1. 期刊 `include_all: true` -> 直接纳入。
2. **金融关键词命中 -> 纳入（对所有期刊）**。
3. **非金融本位刊（`category: management_stats`：JASA、JBES、J.Econometrics、
   Operations Research、Econometrica、Management Science）：到此为止，仅金融关键词算
   数**。原因：这些刊以通用统计 / ML / OR 论文为主，若采用通用方法词或金融主题，会把
   大量非金融论文误纳，再被 `select` 按引用顶上来（实测 JASA 会从约 10 篇真金融膨胀到
   400+ 篇通用方法论文）。OpenAlex 还会给通用时间序列 / 极值论文过度赋上金融类主题，
   故主题在这些刊不可靠。
4. **金融本位刊（core_finance / microstructure_quant）**：金融主题、通用方法主题、通
   用方法关键词也算数（宽口径，契合「所有量化相关」）。

部分词在金融语境与通用语境同形（如 `factor model`、`momentum`），归入通用组，使其只
对金融本位刊生效，避免污染非金融刊。每篇论文记录 `is_quant` 与 `relevance_reason`
（命中依据，如 `finance-kw:garch`、`finance-topic:volatility`、`general-kw:...`、
`no-finance-signal`），便于审查与调参。

实测口径效果（2020-2024）：JFE（金融刊）约 56% 纳入（宽）；JASA（统计刊）从 968 篇中
仅纳入约 10 篇金融计量论文。因此非金融本位刊只贡献其真实金融产出（较少），2100 为上
限，实际语料以金融本位刊为主。

## 5. 架构与数据流

```
config/journals.yaml ─┐
config/settings.yaml ─┤
                      ▼
         ┌──────────────────────────┐
         │ resolve-sources          │  ISSN → OpenAlex Source ID（缓存入库）
         └──────────────────────────┘
                      ▼
         ┌──────────────────────────┐
         │ harvest                  │  按 source + 年份窗口游标分页迭代 works，
         │                          │  重建摘要，记录引用数，相关性筛选，upsert
         └──────────────────────────┘
                      ▼
         ┌──────────────────────────┐
         │ select                   │  每个（期刊, 年份）单元内，对量化论文按
         │                          │  cited_by_count 降序取前 top_per_year 篇，
         │                          │  置 selected=1（其余仅留元数据，不下载）
         └──────────────────────────┘
                      ▼
         ┌──────────────────────────┐
         │ resolve-pdfs             │  对入选量化论文定位开放获取 PDF：
         │                          │  OpenAlex OA → Unpaywall → Semantic
         │                          │  Scholar → OpenAIRE → CORE → arXiv
         └──────────────────────────┘
                      ▼
         ┌──────────────────────────┐
         │ download                 │  限速 + 重试下载，PDF 校验，sha256，
         │                          │  去重，断点续传
         └──────────────────────────┘
                      ▼
         ┌──────────────────────────┐
         │ report                   │  CSV / Markdown 汇总
         └──────────────────────────┘
```

各阶段均幂等、可断点续跑：状态记录在 SQLite，重跑只处理未完成项。

## 6. 目录结构

```
QuantCrawler/
├── CLAUDE.md                 本文件
├── README.md
├── requirements.txt
├── config/
│   ├── journals.yaml         期刊注册表
│   └── settings.yaml         mailto、限速、日期范围、相关性关键词与主题白名单
├── quantcrawler/
│   ├── config.py             配置加载
│   ├── models.py             Paper 等数据结构
│   ├── db.py                 SQLite catalog（papers / journals 表）
│   ├── http.py               带限速与重试的 HTTP 客户端
│   ├── openalex.py           source 解析、works 迭代、摘要重建
│   ├── relevance.py          量化相关性筛选
│   ├── resolvers/            PDF 来源解析器（openalex_oa / unpaywall /
│   │                         semantic_scholar / openaire / core / arxiv）
│   ├── downloader.py         PDF 下载、校验、去重
│   ├── pipeline.py           各阶段编排
│   └── cli.py                命令行入口
├── data/                     运行时产物（git 忽略）
│   ├── catalog.sqlite
│   ├── pdfs/<journal_slug>/<year>/<doi_slug>.pdf
│   └── reports/
└── tests/
```

## 7. 数据模型（SQLite）

`papers` 表主要字段：

- `openalex_id`（主键）、`doi`、`title`、`authors`（JSON）、`journal_slug`、
  `journal_name`、`publication_year`、`publication_date`
- `abstract`、`primary_topic`、`topics`（JSON）、`oa_status`、`cited_by_count`
- `is_quant`、`relevance_reason`、`selected`（是否在每刊每年前 20 之内）
- `pdf_source`（openalex / unpaywall / arxiv / none）、`pdf_url`、`pdf_path`、
  `sha256`、`download_status`（pending / downloaded / paywalled / failed）、`error`
- `harvested_at`、`updated_at`

`journals` 表：`slug`、`name`、`issn`、`source_id`、`category`、`include_all`、
`works_count`、`resolved_at`。

## 8. 命令行用法

```
python -m quantcrawler resolve-sources          # 解析并缓存期刊 Source ID
python -m quantcrawler harvest [--journal SLUG] # 采集元数据 + 引用数 + 相关性筛选
python -m quantcrawler select                   # 每刊每年按引用数取前 20，置 selected
python -m quantcrawler resolve-pdfs             # 为入选论文定位开放获取 PDF
python -m quantcrawler download [--limit N]     # 下载入选论文 PDF
python -m quantcrawler report                   # 生成 CSV / Markdown 报告
python -m quantcrawler run                       # 顺序执行全流程
python -m quantcrawler stats                     # 打印库内统计
```

通用参数：`--config`（配置目录）、`--db`（数据库路径）、`--journal`（限定单刊）、
`--since`（起始日期，默认 2020-01-01）。

## 9. 工程约束

- Python 3.11+（开发于 3.13，conda）。依赖最小化：`httpx`、`pyyaml`，其余用标准库
  （`sqlite3`、`xml.etree`、`argparse`、`hashlib`、`logging`、`concurrent.futures`）。
- 对外请求遵守 polite pool：所有 OpenAlex / Unpaywall 请求携带 `mailto`，按主机限速并
  指数退避重试。失败可恢复，不中断整体流程。
- 代码与注释不使用表情符号，标点使用常规符号，不使用 em dash。
- 所有阶段幂等可续跑；网络与磁盘产物均可安全重入。

### 9.1 并发与健壮性（ultracode 审计后实现）

经多智能体审计（5 维并行审查 + 对抗核验，产出 16 条已核验问题）后落地的下载流水线
优化：

- **按主机线程安全限速**（`http.py:HostRateLimiter`）：不同主机可并发，单一主机仍受
  配额约束；arXiv（`export.arxiv.org` / `arxiv.org`）单独限到 1 rps，避免 429 / 封 IP。
- **并发 resolve-pdfs 与 download**（`ThreadPoolExecutor`，默认 12 线程）：工作线程仅
  做网络与文件 IO，写库统一在主线程，保证 SQLite 单线程访问与续跑安全。配置见
  `settings.yaml` 的 `resolve_workers` / `download_workers`。
- **流式下载 + 体积上限**（`downloader.py` + `http.stream_to_file`）：逐块写入临时
  文件，首块即校验 `%PDF` 魔数，超过 `max_pdf_bytes`（默认 50MB）中止，增量计算
  sha256，原子 `replace` 落盘。避免大文件全量入内存。
- **获取覆盖率（多源候选链）**：下载请求带 `Accept: application/pdf`；按
  Unpaywall -> Semantic Scholar -> OpenAIRE -> CORE -> arXiv 依次解析。前三者为免密
  钥快源（Unpaywall 优先返回仓库 PDF 直链 `url_for_pdf`，Semantic Scholar 常给 arXiv /
  PMC 直链，OpenAIRE 补机构库 .pdf）；CORE 与 arXiv 标题搜索仅在前面都没拿到直链时才
  跑，既省请求又降误匹配。CORE 还须过滤其 `downloadUrl` 中混入的出版社付费链接，优先
  取 `core.ac.uk/download/<id>.pdf` 自托管直链（不经 Cloudflare）与机构库 .pdf。
- **下载失败不污染原链接**：兜底候选失败时保留库中原始 `pdf_url` / `pdf_source`，避免
  重试丢失 OpenAlex 原始 OA 链接。
- **Retry-After 封顶**（默认 120s）并支持 HTTP-date，防止被服务端拖成超长阻塞。
- **内省式数据库迁移**：以 `_PAPERS_COLUMNS` 为单一事实来源，旧库自动补齐缺列。

性能特征：1788 篇带 OpenAlex OA 候选的论文并发下载快；其余约 2800 篇经 Unpaywall
（快）、Semantic Scholar、OpenAIRE、CORE 与 arXiv（均较慢，按主机限速，主要耗时）补充
解析。开放获取命中率受出版社限制，金融顶刊约 10-20%（如 OUP/Wiley/Elsevier 直链多被
Cloudflare 拦截），其余进失败清单走校园网。多源补充后，全量 4590 篇相关论文已下载
OA 副本 961 篇（约 21%）；CORE 一轮 `resolve-pdfs --retry` 净增 24 篇（23 篇为
`core.ac.uk` 自托管直链、1 篇机构库），另有 11 篇为重试时 unpaywall / S2 / OpenAIRE
重新命中。

CORE 鉴权与限速：v3 接口匿名可用但限速极严。免费注册层实测为固定窗口 10 请求 / 60 秒
（响应头 `x-ratelimit-limit: 10`，耗尽后约 60s 重置），故带 `CORE_API_KEY` 时
`api.core.ac.uk` 限到 0.15 rps（约 9/min，安全留在窗口内），匿名层限到 0.1 rps（见
`pipeline._meta_host_rps`）。解析器以 Bearer 提交 key（在 <https://core.ac.uk/services/api>
免费注册）。该 10/min 上限是 CORE 兜底解析的吞吐瓶颈：对数千篇待解析论文，CORE 阶段
耗时以小时计，但幂等可续跑。

## 10. Paper Digest 种子语料（补充发现轴）

参考来源：Paper Digest「Most Cited Papers on Algorithmic Trading / High-Frequency
Trading」榜单，以及 `docs/引用最高的500篇高频交易算法交易论文合集和总结分析.pdf`。

榜单地址：
<https://resources.paperdigest.org/2025/01/paper-digest-most-cited-papers-on-algorithmic-trading-high-frequency-trading/>

### 10.1 对参考资料的分析结论

- **网页榜单可用、结构清晰**：表格共 76 行，无分页。每行含 标题、IF 评分、作者、
  来源期刊、日期，以及一个 `View` 链接，指向该论文的 DOI 落地页（如
  `https://doi.org/10.1016/J.FINMAR.2013.05.003`）。可单次请求抓取后解析。
- **PDF 附录是同一份榜单的完整版**：含约 500 条（500 个 `IF:` 标记），字段同上，
  且来源字段包含 `arxiv-q-fin.TR` 等，表明相当一部分论文托管在 arXiv，可直接下载。
  PDF 文本排版错乱（标题、IF、动作链接、摘要、作者、来源日期交错），解析保真度低于
  网页，但更完整且可离线使用。
- **PDF 中的「API / 下载」内容不是爬虫方法，不予采用**：经核查，这些关键词来自文中
  嵌入的一段第三方加密货币数据贩卖广告（Tardis 数据，含微信联系方式与 VIP 租赁
  报价），与论文抓取无关，属于噪声，按设计忽略。

### 10.2 整合设计

新增一个**种子发现轴**，与第 5 节的期刊枚举轴并存、互补：

- **轴 A（已实现）**：按 ISSN 枚举 12 个顶刊 2020 年至今的全部量化论文。
- **轴 B（本节，待实现）**：以 Paper Digest 榜单为种子，逐篇按 DOI（缺失时退化为
  标题）经 OpenAlex 规范化，再进入**同一套** OA 解析与下载流程（Unpaywall / arXiv）。

种子摄取两种方式：

1. **网页方式（主）**：抓取榜单 HTML 表格，提取 标题 / 来源 / 日期 / DOI。单次请求，
   本地缓存，礼貌限速，遵守 robots 与站点条款。
2. **PDF 方式（补充 / 离线）**：解析 `docs/` 内 PDF 附录的 500 条，按 `IF:` 标记切分
   条目。作为网页方式的离线兜底与扩展。

落地为 `quantcrawler/seeds/paperdigest.py`，产出标准 `Paper` 记录（`journal_slug` 记
为来源期刊或 `paperdigest-seed`，并打标 `source=paperdigest`、`seed_rank`、`seed_if`），
upsert 入同一 SQLite，复用 resolve-pdfs 与 download 阶段。新增命令
`python -m quantcrawler seed-paperdigest`。

### 10.3 与主线范围的关系（已确认口径）

Paper Digest 榜单跨越本项目「顶刊 2020 年至今」范围之外：

- 含大量 2020 年之前的经典文献（如 1988、2000、2011 年）；
- 含不在 12 刊清单内的来源（Econometrica、JPE、arXiv 等）。

**已确认采用「独立补充语料 + 增强筛选器」口径**：

1. **独立补充语料**：将榜单作为单独标注的语料全量纳入（不限年份 / 期刊），打标
   `source=paperdigest`，下载其 OA 副本（多在 arXiv）。这批语料与轴 A 在库内共存但可
   按 `source` 区分统计与报告。
2. **增强筛选器**：抓取后挖掘这批论文的 OpenAlex 主题与标题 / 摘要高频词，据此扩展
   第 4 节的量化主题白名单与关键词，提升轴 A（12 刊）的量化召回。扩展前后均记录命中
   率变化，避免引入过宽的误命中。

（备选口径「仅增强筛选器」与「仅独立补充语料」已排除。）

### 10.4 合规

种子轴仍只下载合法 OA 副本：arXiv 托管者可直接获取，SSRN / 出版社付费墙者只记元数
据。对 Paper Digest 网页仅做单页、低频、带缓存的抓取，不复制其内容用于再发布。

## 11. 实现现状

- [x] 项目骨架与配置（`config/`、`quantcrawler/` 包）
- [x] OpenAlex 元数据采集（source 解析、works 游标分页、摘要重建）
- [x] 量化相关性筛选（主题白名单 + 关键词，偏向召回）
- [x] PDF 解析与下载（OpenAlex OA / Unpaywall / Semantic Scholar / OpenAIRE / CORE /
      arXiv 多候选，PDF 校验、sha256、断点续传）
- [x] CLI 与端到端验证（单元测试 10/10 通过；单刊端到端跑通）
- [x] 期刊清单扩至 21 本（20 本顶刊 + JFI；含引用数采集所需配置）
- [x] 框架：采集时间窗口 2020-2024，harvest 记录 `cited_by_count`
- [x] 框架：`select` 阶段（每刊每年按引用数取前 20，置 `selected`），下游仅处理入选项
- [x] Review of Finance 的 Crossref 补采（`crossref.py`，引用数用 is-referenced-by-count）
- [x] DB 迁移（旧库自动补列），select 单元测试，OpenAlex 与 Crossref 两路端到端跑通
- [x] 主题收窄到四方向（exclude_topics）、窗口 2020-2026、download_scope=all、失败清单
- [x] 全量采集 21 刊（paper_list.csv 共 4590 篇相关论文）
- [x] ultracode 审计 + 下载流水线优化（并发、流式、按主机限速、获取覆盖、内省迁移；
      见 9.1；16/16 单元测试通过）
- [x] 补充 OA 来源：Semantic Scholar、OpenAIRE、CORE 解析器，与 `resolve-pdfs --retry`
      （重置 paywalled/failed 回 pending 再榨一遍）。OA 命中从约 497 经 S2/OpenAIRE 提升
      到 926，再经 CORE 一轮全量 --retry 提升到 961（CORE 净增 24，其他源重试补 11）
- [x] 全量下载收尾：OA 副本 961 篇落入 `data/pdfs/`，其余 3629 篇入 `download_worklist.csv`
      （付费墙 2841 + 失败 788），走校园网 / 人工。CORE 受 10 请求/分钟限速，全量 --retry
      解析约 6 小时
- [ ] 轴 B：Paper Digest 种子语料连接器（见第 10 节，待实现）
- [ ] 待办优化（审计 P2/P3，未实现）：OpenAlex 多候选持久化 pdf_candidates、arXiv DOI
      校验与 Jaccard 放宽、关键词复数/屈折召回、exclude_topics 次级主题、harvested_at 入
      preserve、selected 模式下 NULL 年份告警

### 已知约束（实测）

- 部分出版社（如 OUP / Oxford Academic）对 PDF 直链启用 Cloudflare 拦截，返回 403。
  OpenAlex / Unpaywall 仍会列出该链接，但无法下载。此类论文仅当存在 arXiv 等预印本
  时才能获得开放副本，否则归为 `paywalled`，仅保留元数据。这是「仅开放获取」范围下的
  预期行为，非缺陷。
- Elsevier（如 JFE）在 OpenAlex 中限制摘要，摘要重建率较低，相关性筛选对该类期刊更
  依赖主题标注与标题关键词。
