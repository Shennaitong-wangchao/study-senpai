## 摘要 / Summary

- 

## 变更类型 / Type of change

- [ ] Bug fix / 缺陷修复
- [ ] Feature / 功能
- [ ] Documentation / 文档
- [ ] Security/privacy hardening / 安全与隐私加固
- [ ] Maintenance / 维护

## 安全检查 / Safety checklist

- [ ] 未包含 API Key、Token、Cookie、数据库文件、聊天日志或私有截图。
- [ ] 示例、测试、截图和 demo 都使用假数据。
- [ ] 除非 PR 明确说明，否则没有改数据库 schema。
- [ ] 如改动核心聊天行为，已描述预期用户影响。
- [ ] 行为变化时已更新文档或示例。

English fallback:

- [ ] I did not include API keys, tokens, cookies, database files, chat logs, or private screenshots.
- [ ] I used fake data for examples, tests, screenshots, and demos.
- [ ] I did not change the database schema unless the PR explicitly documents it.
- [ ] I did not change core chat behavior without describing the expected user impact.
- [ ] I updated docs or examples when behavior changed.

## 验证 / Verification

- [ ] `python3 scripts/mobile_contracts.py`
- [ ] `python3 scripts/dashboard_contracts.py`
- [ ] `python3 scripts/verify_product.py`
- [ ] 如改动 iOS 文件，已检查 iOS build / iOS build checked, if iOS files changed

## 给 Reviewers 的备注 / Notes for reviewers

- 
