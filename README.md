# AIBEEP 增长资讯站

面向广告投放/企业获客/AI+增长从业者的每日资讯站。前端已完成，需要你补后端采集。

## 项目结构

```
index.html    — 前端单文件，已完成
data.json     — 数据文件，采集脚本输出到这里
```

## 前端数据格式

前端从同目录 `data.json` 读数据。格式是一个 JSON 数组，每条字段如下：

```json
{
  "id": 1,
  "ch": "dj",              // 平台：dj=巨量引擎 tx=腾讯广告 ks=快手磁力 xhs=小红书 hw=海外投放
  "t": "today",            // today=今天 week=近7天
  "tag": "acq",            // 方向：ad=广告投放 acq=企业获客 mkt=营销方法 ai=AI+增长
  "cat": "platform",       // 栏目：platform=平台动态 data=行业数据 ai=AI营销工具 case=投放案例 acq=获客趋势
  "title": "标题",
  "desc": "一句话摘要",
  "content": "正文（详情抽屉里显示）",
  "src": "来源名称",
  "time": "09:12",
  "heat": 874,
  "focus": 0,
  "st": false,
  "url": "原文链接",
  "score": 86,             // AI评分 0-100
  "co": 1,
  "reason": "推荐理由（橙色底块显示在标题下面）",
  "orig": "原始内容"
}
```

## 需要你做的事

1. 写 Python 采集脚本（`scraper.py`），抓以下平台官方博客/更新日志：
   - 巨量引擎（巨量学/巨量引擎官网更新日志）
   - 腾讯广告（腾讯广告官网/腾讯营销洞察）
   - 快手磁力（磁力引擎官网）
   - 小红书（小红书商家中心/小红书商业动态）
   - Meta Ads（Meta for Business 官方博客）

2. 抓到原文后，调 DeepSeek API 做三件事：
   - 分类：platform/data/ai/case/acq
   - 写一句摘要（desc）
   - 写推荐理由（reason）

3. 输出成 `data.json`，格式和上面一致

4. 写 GitHub Actions 配置（`.github/workflows/daily.yml`），每天早8点自动跑脚本，跑完提交 data.json 到仓库

5. 配置 GitHub Pages 发布

## 注意

- 不要改 index.html 的结构，只加后端
- data.json 为空数组时前端会自动 fallback 到内置示例数据
- API key 用 GitHub Secrets 存，不要硬编码
