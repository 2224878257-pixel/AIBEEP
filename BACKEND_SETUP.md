# 后端运行

## 稳定性与观察记录

AI 使用非思考模式，输出预算 4000 tokens；截断、JSON 或字段校验失败最多重试 3 次，HTTP 401/403 不额外重试。质量不达标是筛除，不作为 API 失败。失败文章保留旧记录，后续采集仍会重审未完成的新版本规则。

新增青瓜传媒、运营派公开 RSS。巨量学（日期缺失）、快手（无公开文章链接）、数英（云端403）暂设 `enabled:false`，配置保留原因，不绕过访问限制；页面会明确显示暂停来源数量。它们尚未修复，不能算作稳定覆盖。

`collection_history.json` 保存最近 90 次运行及最多 30 天日汇总，网页可展开查看最近 3 个有记录的日期。新增、更新、质量筛除、正文重复、已知 URL 跳过、整轮失败、来源异常分别统计；同一天多次运行会累计。现在开始记录，接下来三天按每日任务自然累计，不伪造过去记录。

## 实操筛选与更新状态

社区文章须同时通过：相关性、实操性、评分至少 75 分、至少一条来源可支持的具体操作。优先投放优化、素材测试、获客成本、落地页转化、归因与案例复盘；预算新闻和泛行业观点会筛除。已有社区文章会按质量规则版本重新审核，避免老内容永久跳过新规则。官方公告保留原有通道。

`collection_status.json` 是不含密钥和详细错误的公开状态文件，记录完成时间、新增/更新/筛除数量、异常来源数量及最近成功时间。页面使用北京时间显示，新增为零时也明确显示零；部分来源异常与整轮失败分别显示。Actions 同时提交并发布状态文件；整轮采集失败只发布状态，保留原数据，并让任务最终报错。

## 行业经验来源

除官方来源外，每天从人人都是产品经理 RSS、数英精选列表、Jon Loomer RSS、WordStream RSS 发现公开文章。它们是行业/作者分享，不代表官方确认。源配置使用 `kind: community`；只保存 AI 提炼的短摘要、作者、来源和原文链接，不保存其全文。网页“查看原文来源”可打开原站。

先按标题/列表上下文筛选投放与增长关键词，再提取正文和原始发布日期，最后由 DeepSeek 判断是否相关且具有具体方法、数据或案例。低于 65 分、泛 AI 新闻、纯推广等会过滤；URL 与正文哈希防止重复收录。`run_report.json` 的 filtered 记录 AI 筛选和正文去重数量。默认保留七天内的文章，不将抓取时间当发布时间。

当前通过这些公开来源自动发现候选，尚未接入通用全网搜索 API，也不抓取登录、付费或私密内容。可在 sources.json 继续添加作者博客和 RSS。每源最多三篇进入本轮处理，控制费用；社区文章按实际主题分配平台，无法归入平台时显示“投放与增长”。

前端 `index.html` 保持原样。采集器只读取官方公开网页，不使用账号 Cookie。

## GitHub 配置

1. Settings → Secrets and variables → Actions → New repository secret，添加 `DEEPSEEK_API_KEY`。
2. 可选 Repository variable：`DEEPSEEK_MODEL`，默认 `deepseek-flash`，可按 DeepSeek 当前模型名调整。
3. Settings → Pages → Source 选择 **GitHub Actions**。
4. Actions → Daily collection and Pages → Run workflow 可立即执行。

每日北京时间 08:00 触发（GitHub 定时任务可能延迟）。采集后提交 `data.json`，再部署 Pages。首次 push 只部署，不消耗 API。公开站点仅包含 index.html/data.json，不发布密钥、代码或运行日志。

## 本地

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m playwright install chromium
$env:DEEPSEEK_API_KEY = "你的密钥"
.venv/Scripts/python scraper.py --browser
```

只检查来源（不调用 AI、不更改 data.json）：`python scraper.py --check-sources --browser --limit 2`。
运行测试：`python -m unittest discover -s tests -v`。

## 数据与故障行为

- `sources.json` 配置六个入口，覆盖五个平台。腾讯使用官方资讯公开列表与富文本详情接口；小红书使用聚光帮助中心公开导航与文档正文接口；其他入口发现官方文章链接。网页正文可用 Chromium 渲染。每日每入口最多检查三篇候选，控制运行时间与 AI 调用量。
- 只收录有正文、可靠发布日期、且在最近七天内的文章。无法读取的登录页、没有日期的页面及过期文章不会作为今日新闻发布。小红书帮助文档使用官方更新时间，并在标题明确标为“帮助文档更新”。
- URL 去重，稳定数字 ID；已收录的 URL 不重复调用 AI。AI 分类、文本、评分都校验后才写入。
- `published_at` 是后端附加字段，供跨天重标记 today/week 和七天过期清理。`heat=0` 表示没有官方热度，不虚构阅读量。`score` 是 AI 实用性评分；`focus=0`、`st=false`、`co=1` 是前端默认值。英文原文保留在 `orig`，中文文章该字段为空，避免前端错误显示“已译中”。
- 每源独立容错，单篇失败不影响其他文章；缺失密钥直接失败并保留原文件；全部正文不可用时保留上次快照。JSON 原子写入，最多保留 200 条。
- 每次输出 `run_report.json`，Actions 保存为 14 天 artifact。只有链接发现全部失败才将来源检查标为失败。部分源失效或零篇新文章可正常完成，须结合报告中的 discovered/readable/added/errors 判断覆盖率。
- 官方页面及公开接口可能变更或要求登录；没有保证每个平台每天都有可采集资讯。快手、Meta 和巨量学特别需要检查运行报告。不会用第三方新闻代替官方正文。

接口参考：[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。
