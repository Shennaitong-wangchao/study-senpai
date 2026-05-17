# 人格注册表设计 / Persona Registry Design

## 中文优先

Study Senpai 当前将人格行为保存在有版本控制的 Python 模块和提示词模板中。计划中的公开方向是数据驱动的人格注册表：将产品代码与人格配置分离，同时避免把私有聊天、私有提示词或用户专属记忆提交到 git。

## 目标

- 让人格身份、语气约束、安全边界和记忆策略保持声明式。
- 支持多个示例人格，而不需要改核心聊天逻辑。
- 通过把私有人格草稿和本地 seed 数据留在 git 外，让公开仓库可以安全 clone。
- 在加载人格文件前使用 schema 检查。

## 建议形态

未来注册表可以使用 YAML 或 JSON，包含类似这些 section：

- `identity`：公开名称、角色、locale 和高层风格。
- `voice`：回复语气、格式偏好和短语级约束。
- `boundaries`：人格必须避免的话题或行为。
- `memory_policy`：什么可以被记住、总结或忽略。
- `examples`：只能使用合成示例，绝不使用真实私密对话。

## 隐私规则

- 不要提交真实聊天、导出对话、私有提示词、seed 记忆、token 或部署专属配置。
- 本地专用人格草稿应保存在被忽略的文件里。
- 测试、文档、demo 和截图都使用合成示例。
- 人格注册表改动属于产品行为改动，发布前需要 review。

## 迁移说明

在注册表 loader 和校验流程实现前，`src/persona/` 下的源码模块和 `src/llm/prompts/` 下的提示词模板仍是事实来源。

## English fallback

Study Senpai currently keeps persona behavior in versioned Python modules and prompt templates. The planned public direction is a data-driven persona registry that separates product code from persona configuration without storing private chats, private prompts, or user-specific memories in git.

Goals: keep identity, voice constraints, safety boundaries, and memory policy declarative; support multiple example personas without changing core chat logic; keep private drafts and local seed data outside git; validate persona files before loading.

Future YAML/JSON sections may include `identity`, `voice`, `boundaries`, `memory_policy`, and `examples`. Examples must be synthetic only.

Do not commit real chats, exported conversations, private prompts, seed memories, tokens, or deployment-specific configuration. Treat persona registry changes as product behavior changes and review them before release.
