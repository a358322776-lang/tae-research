# TAE 研究仓库

用途：Muse 与 ChatGPT 共享 TAE 策略研究资料，减少人工复制粘贴。
本仓是研究资料仓，不是执行系统。
2026-10-25 起为公开仓库：策略与交易记录对全网可见；凭证与执行器运行时仍永不进仓。

铁律（写死，不经主人批准不得改）：
1. 研究仓与真钱执行器物理隔离。执行器只读 VPS 本地扫描器代码，
   绝不从本仓拉取任何规则或代码；改了仓里的文件，实盘不会跟着变。
2. 策略规则变更须主人明确批准。v4.1 现行冻结，任何调参、加规则、
   删规则都必须先经主人点头，再记入 rules/CHANGELOG.md。
3. 凭证永不进仓：.env、密钥、state、events、.live-ok 一律禁入，
   导出只按 export-allowlist.txt 白名单，提交前跑 scripts/check-secrets.sh。
4. 零额外 API 成本：同步只用免费 git + GitHub 私有仓，不调任何付费 API。

交换方式：
- Muse <-> 本仓：全自动，git 读写。
- ChatGPT <-> 本仓：有 GitHub 连接器则直接读写；否则走
  reviews/review-requests/（一次一贴）与 reviews/gpt/（回复归档）两次粘贴模式。
