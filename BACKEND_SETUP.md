# AIBEEP 后端 V1｜本地验证与后续部署

本版不依赖域名或 ICP 备案。它不是云端后端：ChatGPT Sites 私有预览继续使用静态 JSON；本地 Python/Docker 运行时会优先请求 `/api/content` 和 `/api/article-bodies`，API 不存在才回退静态内容。

## Windows 本地启动

推荐安装 Docker Desktop 后，在项目目录执行：

```powershell
Copy-Item .env.example .env
# 只在本机编辑 .env，设置 DEEPSEEK_API_KEY 和随机 AIBEEP_ADMIN_TOKEN

# 两阶段 AI：正文生成和独立审核默认均使用 deepseek-flash。
# 旧名称 deepseek-chat / deepseek-reasoner 已停用，请勿沿用老教程配置。
docker compose up -d --build
docker compose logs -f scheduler
```

打开 `http://127.0.0.1:8080`。内容接口：`/api/health`、`/api/content`、`/api/article-bodies`。数据库存放在 Docker 命名卷 `aibeep-data`；启动时导入现有九条示例资料，重复启动不重复写入。

未装 Docker 的电脑可运行 `python backend.py`，默认监听 `127.0.0.1:8080`。然后单独执行 `python scheduler.py --once`；若没有配置 DeepSeek 密钥，只抓取候选资料，不做审核和发布。Python 版使用项目下 `data/aibeep.sqlite3`。

## 自动抓取审核机制

1. 每 6 小时拉取配置中的官方 RSS/Atom，去重后写入候选队列。
2. 配置了密钥才会运行 DeepSeek 中文内容整理和独立的原始来源核对。
3. **双重硬条件**：`reviewStatus=approved` 且 `audit.decision=approved`。其余候选（包括 AI 错误、事实不足、版权风险、低相关性）一律不公开。
4. 已通过门禁的原创中文整理稿才写入 SQLite，网站从数据库读出；保留官方原文链接和出处。不要把第三方全文直接转载。

注意：目前采用官方 HTML 提取做来源依据，不能保证每个源都能抓取完整资料；无证据则保留待复核。AI 审核不是法律意义上的内容合规担保。站点正式公开运营前需结合实际业务形态确认浙江个人备案是否合适、是否触发增值电信/互联网信息服务相关资质与备案要求。

## 安全边界

- 密钥仅保存在服务端环境变量 `.env`，不上传 GitHub，不在网页 JavaScript 中使用。
- 管理端写入要求不少于 32 字符的 `AIBEEP_ADMIN_TOKEN`；默认未设置时管理接口不可用。
- Docker 端口只绑定 Windows 本机回环地址，**并未对公网开放**。
- 首期 SQLite 减少成本，稳定运行并确认备案与发布模式后迁移 PostgreSQL；迁移时保持 API 不变。
- 正式上线前必须再补充速率限制、任务队列、备份恢复测试、审计日志与 HTTPS 反向代理。

## 下一步

1. 腾讯云备案客服书面确认：杭州个人备案能否如实运营“广告投放与 AI 企业增长信息整理网站”，若个人身份适用，身份证住址非浙江需准备居住证/居住证明。
2. 确认后再实名购买 `aibeep.cn`（截图显示尚可注册；价格以结算页为准），以及满足接入要求的中国大陆备案服务器。网站名称须符合个人备案命名规则，不能只填纯英文 AIBEEP。
3. 备案完成前继续本地/私有环境验证。公开部署要单独配置域名、证书、数据库备份与网站安全策略。

## V14 信源扩展与监控

信源登记在 `feed_sources.json`，分两种模式：

- `feeds`：3 条已登记 RSS，自动采集标题、摘要和官方来源链接。先执行关键词相关性预筛，再交由 DeepSeek 依据原始资料独立审核。
- `watch_pages`：9 个国内及海外广告平台官方页面。**只是待接入名单，不代表已实现自动抓取**；这些页面没有经过官方 RSS 或 API 稳定性验证，禁止以网页全文无差别抓取、复制和公开发布。

采集运行后，`source_status.json` 会记录每个 RSS 的成功、失败、新候选、过滤数量，便于排障（不存入 Git）。登录本地后端可通过 `GET /api/sources` 查看公开信源目录；管理员携带 Bearer token 调用 `GET /api/admin/status` 读取采集统计。`/api/admin/status` 不对匿名用户开放。

离线回归测试：`python3 -m unittest test_pipeline.py -v`。当前 Sites 私有预览是静态托管，不会自动运行 Python 抓取或数据库；需启动 Windows 本地 Docker 或后续专门后端服务，才能让新文章自动出现在站内。
