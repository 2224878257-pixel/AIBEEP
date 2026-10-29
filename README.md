# AIBEEP V16

面向广告投放、AI 营销与企业增长从业者的资讯工作台。系统从允许访问的官方 RSS 获取候选内容，经相关性初筛、DeepSeek 中文整理和独立事实审核后，只有满足严格门禁的条目才能写入公开静态数据。

## 安全边界

- `DEEPSEEK_API_KEY` 只从服务器环境变量或 GitHub Actions Secret 读取，禁止写入仓库和 `dist/`。
- AI 审核不是法律审查，也不等同于站外事实核查；发布前仍需人工确认来源、版权和合规。
- GitHub Pages 默认关闭。只有仓库变量 `AIBEEP_ENABLE_PUBLIC_PAGES=true` 且人工手动触发部署工作流时才允许发布。
- 候选、审核失败和处理异常不会进入 `dist/content.json` 或 `dist/articles.json`。

## 本地离线验证

```bash
python -m unittest test_pipeline.py -v
python -m json.tool dist/content.json
python -m json.tool dist/articles.json
```

GitHub Actions、DeepSeek Secret 和 Pages 配置见 [GITHUB_V16.md](GITHUB_V16.md)。
