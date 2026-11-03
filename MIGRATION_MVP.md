# AIBEEP 最小可用版审计与回滚

基线：b2c074f2924d3c741a2197211561adf27901896e。

推送前已合并定时采集提交 afd3f34，合并后的 50 条历史记录作为保留基线，不覆盖今早新增内容。初始审计的 40/44 是合并前快照。

用户最新要求优先只修改 AIBEEP；个人网站仅审计、检出源码，不修改或部署。

## 真实状态
- AIBEEP 仓库：2224878257-pixel/AIBEEP，Pages 自定义域名 aibeep.cn，HTTPS 已开启；现有数据 40 条，归档 44 条，基线 38 项测试通过。
- 个人网站仓库：2224878257-pixel/2224878257-pixel.github.io，Pages main 根目录发布，域名 houyuping.cn，HTTPS 已开启；有 13 篇文章元数据、14 个 articles HTML 文件（含列表页）。正常浏览器探测根域名受到 Cloudflare 403 拦截，不能声称公网访问验证通过。
- 个人站现有可靠入口：X https://x.com/LaohouGrowth、小红书 https://xhslink.cn/o/6GBc3jNCZAJ、抖音 https://v.douyin.com/vRrS_vDoSOk/，邮件 2224878257@qq.com。不编造公众号/B站主页 URL。

## 复用资产
静态单页、数据/历史归档、收藏与阅读状态、来源及日期、图片与二维码过滤、OCR、Python 采集适配器、DeepSeek 调用、GitHub Actions 和 Pages 全部保留。原 cat/ch 字段、文章 id/url 不改；新 schema 使用独立字段，旧记录按历史栏目读取。密钥不读取、不迁移、不覆盖。

## 回滚
代码使用增量提交；可对本次功能提交执行 git revert 并推送，Actions 会重新部署。不要 git reset/强推，也不要清空新产生的数据。仅回退 index.html、scraper.py、discovery.py、sources.json 和工作流等代码文件可保留后续文章；新字段对旧前端无影响。审核队列不作为 Pages 文件发布。

本次 MVP 范围：优先 AIBEEP。个人站只增加出站入口，不声称已经完成个人站反向链接、首页或商务页改造。网站 JSON 保留 cat/ch/id/url；新增 section/discovery_category/discovery_details/detail_kind 及独立状态。赚钱项目和方法一律待审，任何含收益宣称的内容也待审；审核队列在 Actions 缓存与 editorial-review-queue artifact 中留存，不提交公开源码、不进入 Pages。

## 本轮结果
- 发布地址：https://aibeep.cn/；新首页正式收录 5 条（4 条 AI 工具、1 条实用信息）。赚钱项目/方法暂不填充未经人工审核的推荐。
- 43 项后端测试通过；线上 1440px 桌面及 390px 手机验证：五分类、搜索、工具与项目详情组件、未知标记、日夜模式持久化、SEO、原有文章详情链接；无页面运行错误。项目详情使用隔离测试数据验证，没有发布虚构项目。
- 对比 afd3f34，原 50 条文章的 id/url 全部保留。原有来源中仍有公众号验证页与 Meta 日期不完整问题，未绕过验证。
- 新增 GitHub 与 Hugging Face 官方 RSS；仅增加来源，不覆盖已有配置和密钥。
- 最小回滚：从 afd3f34 恢复 index.html、scraper.py、sources.json、.github/workflows/daily.yml 等代码文件，提交后正常推送；不要恢复或删除 data.json/archive.json/assets，以保留迁移后新增数据。辅助新增模块可保留为未调用文件。需整体撤销功能时，按逆序 git revert 功能代码提交，处理数据保留冲突后再部署，禁止 reset/强推。
