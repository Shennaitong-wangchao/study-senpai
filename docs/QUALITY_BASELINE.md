# 质量基线 / Quality Baseline

## 中文优先

这份文档定义 Study Senpai 当前公开协作前的质量、安全和发布验收基线。它不是“项目已经生产就绪”的声明，而是维护者和贡献者判断改动是否让项目更安全、更可测、更可审计的共同口径。

最后验证日期：2026-06-11。

## 当前验收命令

每次合入前至少运行：

```bash
python -m pytest
python scripts/release_gate.py
python scripts/mobile_contracts.py
python scripts/dashboard_contracts.py
python scripts/verify_product.py
python scripts/verify_prompt_caching.py
```

安全和质量审计使用：

```bash
python scripts/release_gate.py
python <senior-security>/scripts/secret_scanner.py . --format json
python <senior-fullstack>/scripts/code_quality_analyzer.py . --json
```

`<senior-security>` 和 `<senior-fullstack>` 指本地 Codex skill 目录。不要把本机绝对路径写进公开 issue、PR 或文档。

## 当前已验证状态

| 项目 | 当前结果 |
|------|----------|
| pytest | 83 passed |
| release gate | passed |
| Mobile API contracts | passed |
| Dashboard contracts | passed |
| product verification | passed |
| prompt caching verification | passed |
| secret scanner | 0 findings |
| code quality analyzer critical | 0 |
| code quality analyzer estimated coverage | 25% |
| documentation score | 100 |
| GitHub Actions | `Python contracts` passing |

## 发布阻断规则

以下情况必须阻断合入或发布：

- `scripts/release_gate.py` 发现本地私有路径、真实密钥、高置信凭据或未脱敏私有状态。
- secret scanner 发现 critical/high 凭据命中，且无法证明是 placeholder 或测试构造。
- pytest、contract、product verification 任一失败。
- 新增公网暴露路径绕过 Dashboard auth、Mobile Bearer Token、CSRF 或现有权限边界。
- 新增日志、trace、Dashboard 页面或 Mobile API 响应泄漏完整聊天内容、密钥、Cookie、数据库路径或本地文件路径。

## 当前已知质量债

| 类别 | 状态 | 处理策略 |
|------|------|----------|
| 静态 high findings | `code_quality_analyzer.py` 当前仍报告一批 broad `sql_injection` high。多数来自 Python logging `%s` 占位符、日期格式 `%d`，或非 SQL 的格式字符串。 | 不把这些宽泛命中当作单独发布阻断项；后续需要引入更精确的 repo-owned SAST 规则或逐项人工 triage。 |
| medium HTTP findings | 多数为本地 demo、localhost 或开发脚本中的 `http://` 示例。 | 公网部署文档必须继续要求 TLS、反向代理、防火墙和 token。 |
| Dashboard HTML rendering | Dashboard JS 仍有 `innerHTML` 类命中。 | 涉及用户内容的渲染必须保持转义或受控模板；后续应拆出统一安全渲染 helper 并补浏览器回归。 |
| 大文件复杂度 | `src/dashboard/server.py`、`src/product/store.py`、`scripts/verify_product.py` 等文件仍偏大。 | 后续优先拆分 contract fixtures、Dashboard route 模块和 ProductStore 子域。 |
| 覆盖率 | analyzer 估算覆盖约 25%，低于长期目标。 | 每次功能改动都补聚焦测试；近期优先补 Dashboard route、ProductStore 查询、presence/proactive/day engine 深分支。 |

## 质量改进路线

### 近期

- 继续把高风险纯逻辑模块补到 pytest：Dashboard route helper、ProductStore 写路径、presence/proactive 分支、reality calendar 解析。
- 将 `scripts/verify_product.py` 拆出 fake data、Dashboard client helper 和断言 helper，降低复杂度。
- 为 Dashboard 用户内容渲染添加统一转义测试，减少 XSS 审计噪声。

### 中期

- 增加 repo-owned security triage 脚本，区分真实 SQL/API 风险、logging/date-format 误报和本地 demo URL。
- 在 CI 中上传覆盖率报告，并设置逐步提升的最低阈值。
- 为 iOS tests 增加独立 CI job 或明确的本地验证脚本。

### 长期

- 引入更精确的 SAST/依赖扫描工具，例如 Semgrep、Bandit、pip-audit 或 GitHub CodeQL。
- 建立 release checklist，要求安全、测试、文档、迁移、隐私影响都有明确勾选。
- 对公开 demo 数据建立固定 fixture，避免任何真实用户状态进入截图、视频或 issue。

## 贡献者检查清单

提交 PR 前确认：

- 新增功能有测试或说明了无法测试的原因。
- 修改 Dashboard/Mobile API 时同步 contract 或产品验证脚本。
- 没有提交 `.env`、SQLite、日志、聊天导出、生成媒体或本地 iOS 私有配置。
- 文档中没有本机绝对路径、真实服务地址、真实用户内容或未脱敏凭据。
- PR 描述写明验证命令和隐私/部署影响。

## English fallback

This document defines the current quality, security, and release baseline for Study Senpai. It is not a production-readiness claim; it is the shared standard for deciding whether a change improves safety, testability, and auditability.

As of June 11, 2026, the baseline is: 83 pytest tests passing, release gate passing, Mobile/Dashboard contracts passing, product and prompt-caching verification passing, secret scanner reporting 0 findings, code quality analyzer reporting 0 critical findings, estimated coverage at 25%, documentation score at 100, and GitHub Actions `Python contracts` passing.

Release blockers include release-gate findings, real credential scanner findings, failed tests/contracts/product verification, auth bypasses, and any new leak of secrets, private paths, private chat content, cookies, database state, or local files.

Known debt remains: broad static high findings from heuristic analyzer rules, local HTTP examples, Dashboard HTML-rendering audit noise, large historical files, and low estimated coverage. These are tracked here so contributors can improve them deliberately instead of normalizing them as invisible debt.
