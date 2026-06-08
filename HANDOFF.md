# 交接说明 / HANDOFF

如何在两台机器之间交接 QuantCrawler，让接手者**无缝衔接**：已经下载过的 PDF 不再重复
下载，直接从断点继续。

## 重要：PDF 不进公开仓库

代码仓库**不包含** PDF 与数据库（`.gitignore` 已忽略 `data/pdfs/` 与 `*.sqlite`）。原因
是版权：「可免费阅读的开放获取」不等于「可公开再分发」，已下载的 PDF 许可类型混杂
（green / hybrid / bronze 等），公开上传有合规风险。

因此 PDF 与下载进度通过**私下传输**交接（移动硬盘、私有网盘、内网等），不经公开 Git。

## 交接方需要打包什么

把运行时数据目录打包发给接手者（这两样就够无缝衔接）：

```bash
# 在项目根目录
tar -czf quantcrawler-data.tgz data/pdfs data/catalog.sqlite
# 通过私有渠道发送 quantcrawler-data.tgz
```

- `data/pdfs/`：已下载的 PDF（按 期刊/年份/DOI 组织）。
- `data/catalog.sqlite`：全部元数据与下载状态（谁下过、来源、sha256、谁还没下）。

## 接手方如何继续

```bash
# 1) 拿到代码（公开仓库即可，不含 PDF）
git clone <repo> && cd QuantCrawler-
pip install -r requirements.txt

# 2) 解包交接数据到项目根目录
tar -xzf quantcrawler-data.tgz        # 还原出 data/pdfs 与 data/catalog.sqlite

# 3) 确认状态（应看到已下载若干篇）
python -m quantcrawler stats

# 4) 从断点继续：已下载的会被自动跳过，不重复下载
python -m quantcrawler resolve-pdfs   # 继续解析未定位的
python -m quantcrawler download       # 只下未完成的
python -m quantcrawler report         # 刷新清单与统计
```

**为什么不会重复下载**：每篇论文在 `catalog.sqlite` 里有 `download_status`；`download`
只挑 `pending` 的处理，`downloaded` 的根本不会被选中。即便被选中，下载器也会先检查目标
文件是否已存在，存在就直接跳过、不发网络请求。

## 兜底：只拿到了 PDF、没拿到数据库

如果只收到 `data/pdfs/`（没有 `catalog.sqlite`），先重建目录再对齐磁盘：

```bash
python -m quantcrawler resolve-sources
python -m quantcrawler harvest         # 重建 catalog（全部为 pending）
python -m quantcrawler reconcile       # 扫描 data/pdfs/，把磁盘已有的 PDF 标记为 downloaded
python -m quantcrawler download        # 只下剩余的
```

`reconcile` 会按 (期刊, 年份, DOI) 的确定性路径检查磁盘上是否已有该 PDF，有则标记为
downloaded 并补算 sha256。路径派生规则两台机器一致，故能正确对齐。

## 付费墙部分（需要校园网）

约 80% 的论文因出版社付费墙 / Cloudflare 拿不到，列在 `data/reports/download_worklist.csv`
（含 DOI 与落地页）。这部分用校园网 / 机构订阅在浏览器里下载，存回
`data/pdfs/<期刊>/<年>/<doi>.pdf`，再跑一次 `python -m quantcrawler reconcile` 即可纳入统计。
具体见 `warmup_brief.html`。
