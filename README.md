# AIBEEP V16.1

面向广告投放、AI 营销与企业增长从业者的资讯工作台。系统从允许访问的官方 RSS、官方前端公开接口和公开网页获取候选内容，经相关性初筛、DeepSeek 中文整理和独立事实审核后，只有满足人工发布门禁的条目才能写入公开静态数据。

## 安全边界

- `DEEPSEEK_API_KEY` 只从服务器环境变量或 GitHub Actions Secret 读取，禁止写入仓库和 `dist/`。
- AI 审核不是法律审查，也不等同于站外事实核查；发布前仍需人工确认来源、版权和合规。
- GitHub Pages 默认关闭。只有仓库变量 `AIBEEP_ENABLE_PUBLIC_PAGES=true` 且人工手动触发部署工作流时才允许发布。
- 候选、审核失败和处理异常不会进入 `dist/content.json` 或 `dist/articles.json`。
- 定时采集和 AI 审核不会自动公开发布。AI 通过的条目仍需写入明确的人工审批元数据，再由人工手动触发发布。

## V16.1 国内信源

- 腾讯广告：官方资讯页前端公开 JSON 接口。
- 巨量引擎：巨量学官方公开网页。
- 小红书聚光/千帆：聚光帮助中心前端公开 JSON 接口。
- 微信广告/本地推/视频号、快手磁力、百度营销：当前保留人工链接，未声明为自动接入。

详细验证结果和合规边界见 [SOURCE_VERIFICATION_V16.1.md](SOURCE_VERIFICATION_V16.1.md)。

## 本地离线验证

```bash
python -m unittest test_pipeline.py -v
python collect_feeds.py --limit 3 --max-age-days 180 --delay 1 --source "腾讯广告" --source "巨量引擎" --source "小红书聚光/千帆"
python report_run.py
python -m json.tool dist/content.json
python -m json.tool dist/articles.json
```

GitHub Actions、DeepSeek Secret 和 Pages 配置见 [GITHUB_V16.md](GITHUB_V16.md)。
