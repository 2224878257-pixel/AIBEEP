# AIBEEP 内容更新流程（审核版）

目标：面向互联网用户展示有出处、可核对的中文原创整理稿。采集队列不等于公开文章。

## 当前可运行

1. `python3 collect_feeds.py` 从 `feed_sources.json` 的官方 RSS / Atom、官方前端公开接口和公开网页抓取元数据，按规范化 URL 与内容指纹去重，生成 `review_queue.json`、`source_status.json` 和 `run_report.json`。
2. 如配置自己的 `DEEPSEEK_API_KEY`，可运行 `python3 collect_feeds.py --ai`，调用 DeepSeek 根据 RSS 标题及摘录生成中文编辑草稿。当前 AI 只处理摘要，不获取或重刊原文全文。
3. 设置 `DEEPSEEK_API_KEY` 后运行 `python3 ai_review.py --limit 5`：程序仅从可信官方域名抓取公开证据、用 DeepSeek 生成原创中文稿、再次独立对照源文审核。相关性至少 80、事实忠实度至少 95、两条以上支持证据、没有重复或风险标记时，AI 审核可标为 `approved`，但发布状态只进入 `pending_human`。否则为 `needs_review` 或 `rejected`，不入站。**这不是外部独立事实核查，也不能完全消除模型误判。**
4. 少量 `needs_review` 内容可人工核对并修改，或直接跳过。
5. 人工核对来源、摘要和证据后，将 `publicationStatus` 设为 `approved`，并填写 `humanApproval.approvedBy` 与 `humanApproval.approvedAt`。
6. `python3 publish_reviewed.py` 先预检；通过后 `python3 publish_reviewed.py --apply` 才可把同时通过 AI 与人工门禁、结构完整的稿件写入 `dist/content.json` 和 `dist/articles.json`，不会重复导入已存在的 ID 或来源链接。
7. GitHub Actions 定时任务执行采集与 AI 审核，但默认只做发布预检；公开数据写入必须由人工手动触发发布输入。

## 后续需要的云端能力

- 周期调度与抓取执行环境；单纯的静态页面不会自动执行本地 Python。
- 数据库存储候选稿、审核状态、失败重试和抓取日志。
- 仅站点管理员可用的审核操作及 API，不放在面向公众的导航中。
- 审核通过后自动写入持久化数据库，由读者页面读取，无需每次重新发布静态站。
- 图片与代码片段支持，只有在来源授权或允许链接展示时使用原媒体；普通第三方新闻保留原文链接和原创梳理。

## 采集规范

- 尊重 robots、来源条款、频率限制与版权；不能访问时记录失败，不尝试绕过。
- 事实与推断分开写，不以 RSS 标题推断完整内容。
- 不能将采集时间冒充文章发布时间，也不能把人工精选标成客观“热度”。
- 信息缺失则保持 `pending`，不得自动发布。
