# AIBEEP V16｜GitHub Actions + DeepSeek + Pages

此版本无需 Windows Docker：GitHub Actions 在云端运行 Python，生成 `dist/content.json` 和 `dist/articles.json`。GitHub Pages 只展示静态文件，不运行 Python / SQLite / 管理接口。

## 上传并配置

1. 新建 GitHub 公共仓库 `AIBEEP`，上传本项目源码（包括 `.github/workflows/`），但不要上传 `.env`、API 密钥、个人数据或本地数据库。
2. 在 **Settings → Secrets and variables → Actions → New repository secret** 添加 `DEEPSEEK_API_KEY`。密钥由仓库所有者在 GitHub 网页输入；不要粘贴到聊天记录、源码、日志或公开 issue。
3. 在 **Settings → Actions → General → Workflow permissions** 确认 `GITHUB_TOKEN` 有可写入仓库内容的权限（适用时选择 Read and write permissions），否则 `refresh-content.yml` 最后提交 JSON 会失败。可选使用受限机器人分支 + PR 审查，进一步降低自动写入主分支风险。
4. 通过 **Actions → AIBEEP official feeds and AI audit → Run workflow** 手动跑第一轮，并检查每个步骤；之后默认每六小时左右自动触发，GitHub 不保证定时精确执行。
5. 运行后只查看 `review_queue.json` 和 `dist/*.json` 是否变化；**不要把自动审核当成完全准确的事实核查**。来源抓取失败或审核不合格会保留而不发布。

## Pages 公开发布门槛

`deploy-pages.yml` 默认不随采集自动公开部署。只有确认业务内容、版权、网站主体和合规要求后，才在 **Settings → Pages → Build and deployment → Source: GitHub Actions** 配置并从 Actions 手动运行 `AIBEEP GitHub Pages (manual release gate)`。

首次发布后，如需每轮抓取成功便自动部署，在仓库 **Settings → Secrets and variables → Actions → Variables** 中新增 `AIBEEP_ENABLE_PUBLIC_PAGES=true`。不设置或设置为 `false` 时，自动部署任务会跳过。此开关只影响网站发布，不能替代合规审核。

GitHub Pages 是静态托管，不能用作主要商业交易或 SaaS 服务的免费后端。更适合本项目初期的免费知识/行业资料展示。

**合规待确认（不能以 GitHub 位于境外直接推定无需备案）：**

- 工信部《非经营性互联网信息服务备案管理办法》（2024 修订）：https://www.miit.gov.cn/gyhxxhb/jgsj/cyzcyfgs/bmgz/xxtxl/art/2024/art_84a0cfa0ebd049bbbe751dca9a008e56.html
- 国家网信办《互联网新闻信息服务许可事项服务指南》：https://www.cac.gov.cn/2019-07/23/c_1565410775838394.htm
- GitHub Pages 服务条款：https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features

网站定位应限制在公开平台**产品文档、广告技术更新和原始官方资料的独立中文分析**，不做社会时政新闻采编、转载平台、未授权全文镜像；发布前需要向主管部门或合格专业人士确认实际业务是否属于备案和前置审批范围。即便只做免费资讯，也不应武断认定不受监管。

## 数据及费用

- 单次审核限 3 条，控制 DeepSeek 消耗；按模型实际价格和调用量收费。并非保证免费。
- GitHub Actions 免费额度、调用限制随账户和仓库设置而变。关注 GitHub Billing。
- `review_queue.json` 随仓库存档；它是候选和审核日志，发布正文写 `dist/*.json`。公共仓库会公开候选与审核结果，避免存放内部业务机密或个人信息。
- 公开仓库任何可读取工作流的人都能审查调用逻辑，避免从不可信 PR 执行带密钥的工作流。不要开启 `pull_request_target` 使用 API 密钥。
- 未来需要用户登录、数据库即时查询或付费 SaaS 时，应迁移到专业托管服务，不能只依赖 Pages。

## 离线测试

`python -m unittest test_pipeline.py -v`

无需 DeepSeek 密钥即可验证审核门禁与 JSON 处理；真实 API 与 GitHub Actions 云端执行必须在你的仓库内验证，不能把模拟测试称为真实联通。
