# AIBEEP V16.1 国内信源验证记录

验证日期：2026-10-29。验证范围仅包含无需登录即可访问的官方页面或官方前端公开 JSON 接口；未绕过登录、验证码、访问控制、反爬或付费墙。

## P0 已接入

| 平台 | 官方入口 | 采集方式 | 验证结果 | 边界与风险 |
| --- | --- | --- | --- | --- |
| 腾讯广告 | `https://e.qq.com/latestnews/` | `official_api`：页面自身使用的 `POST /portal/information/new_search`，详情使用 `GET /portal/case_center/posts` | HTTP 200，可取得真实标题、时间、详情 URL 和正文证据 | 不是承诺稳定的开放 API，接口变化时失败关闭；仅低频读取，无登录 |
| 巨量引擎 | `https://school.oceanengine.com/` | `public_webpage`：解析服务端渲染的官方课程/直播链接 | HTTP 200，可取得官方标题、时间和原始链接；`robots.txt` 当前允许 `/` | 不调用私有接口，不抓取需登录内容；页面结构变化时记录失败并隔离 |
| 小红书聚光/千帆 | `https://ad.xiaohongshu.com/next_help/home` | `official_api`：帮助中心前端使用的 `/api/light/help/doc/space/nav` 与 `/api/light/help/doc/content` | HTTP 200，可取得真实帮助文档标题、更新时间、路径和正文证据 | 不是承诺稳定的开放 API，接口变化时失败关闭；不访问商家后台或账户数据 |

首次真实小批量采集共读取 57 条：腾讯广告 24 条、巨量引擎 9 条、小红书聚光/千帆 24 条。初筛生成 25 条候选、过滤 32 条；规则复核后又将 3 条主题不足的候选标记为 `rejected/withheld`，不会进入公开数据。该次运行没有调用 DeepSeek，也没有修改 `dist/content.json` 或 `dist/articles.json`。

2026-10-30 对同一来源再次执行验证：仍读取 57 条，识别 24 条重复、过滤 32 条，并发现 1 条刚更新的官方新文档。该结果证明已有内容不会重复入队，同时新发布内容仍可进入候选队列。三个来源均为 HTTP 200，失败来源为 0。

## P1 暂保留人工链接

微信广告/本地推/视频号广告、快手磁力引擎、百度营销仍为 `manual_link`。原因是本轮尚未找到并验证同时满足“官方、无需认证、稳定提供资讯列表/时间/原始证据”的自动入口。配置保留官方入口和人工提交能力，不用猜测 RSS 或伪造 API。后续必须逐个平台重新验证 robots、使用条款、页面结构和访问稳定性后才能转成自动来源。

## 发布与证据门禁

- 采集候选必须保留标准化原始 URL、来源、平台、发布时间、采集时间和摘要证据。
- URL、规范化 URL 和内容指纹共同去重；单个来源异常不会终止其他来源。
- DeepSeek 仅处理候选，并独立输出相关性、重复性、证据一致性和审核理由。
- AI 通过后状态为 `pending_human`。只有包含明确 `humanApproval.approvedBy`、`approvedAt` 且 `publicationStatus=approved` 的条目，才有资格执行发布。
- 定时任务不再自动执行公开发布；人工手动触发并勾选发布输入后，仍需通过上述数据门禁。

机器可读的单次结果保存为 `run_report.json`，每个来源的 HTTP 状态、抓取量、重复量、过滤量、成功率和错误保存在 `source_status.json`，Actions 同时上传报告工件。
