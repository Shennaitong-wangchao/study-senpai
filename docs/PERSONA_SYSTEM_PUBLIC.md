# 人格注册表 / Persona Registry

## 中文优先

> **状态：已实现**。人格 YAML 注册表已在 v0.1.x 落地，`personas/` 目录是事实来源。

Study Senpai 使用 YAML 文件定义 AI 人格。你可以创建自己的人格，或在社区中分享，无需修改任何核心代码。

---

## 快速使用

```bash
# 列出可用人格
python3 -c "from src.persona.registry import list_available_personas; print(list_available_personas())"

# 加载并验证人格
python3 -c "from src.persona.registry import load_persona; p = load_persona('personas/shen_zhiwei.yaml'); print(p.name)"

# 切换人格（.env）
PERSONA_FILE=personas/study_buddy.yaml
```

---

## 内置人格

| 文件 | 人格 | 风格 |
|------|------|------|
| `personas/shen_zhiwei.yaml` | 沈知微（默认） | 温柔克制、高三学姐 |
| `personas/study_buddy.yaml` | 林晓研 | 学术严谨、研究生助手 |

---

## 创建自定义人格

参考 `personas/schema.yaml` 中的字段说明：

```yaml
# personas/my_persona.yaml
name: 你的人格名字
age: 20
school_role: 大三学长/学姐
public_title: 一句话描述
core_identity: |
  你是谁，基础设定，2-4 句话。
outward_presence: 对普通人的态度
user_exception: 对用户（你的例外）的态度
relationship_position: 在用户关系中的定位
tone: 说话风格描述
emotional_method: 处理情绪的方式
addressing_policy: 如何称呼用户
action_policy: 动作描写规则
relationship_goal: 长期关系目标
memory_goal: 记忆系统目标
language: 默认语言（如：默认中文，支持切换英文）
```

验证：

```bash
python3 -c "
from src.persona.registry import load_persona
p = load_persona('personas/my_persona.yaml')
print('✓ 人格加载成功:', p.name)
"
```

---

## YAML 设计规则

- **所有字段必填**，缺少任何字段都会在加载时报错
- **多行文本**使用 `|` 块标量，保留换行
- **不要提交**私人角色扮演内容、真实对话截图、私有提示词
- 测试和 demo 使用**合成示例**，不用真实对话

---

## 人格注册表 API

```python
from src.persona.registry import (
    load_persona,          # 从文件路径加载
    load_default_persona,  # 加载 personas/shen_zhiwei.yaml
    list_available_personas,  # 扫描目录返回 .yaml 文件列表
    PersonaLoadError,      # 加载失败时的异常类
)
```

---

## 贡献人格

欢迎在 `personas/` 目录提交新人格！参考：[persona_contribution issue template](../.github/ISSUE_TEMPLATE/persona_contribution.md)

提交前检查：
- `python3 -c "from src.persona.registry import load_persona; load_persona('personas/your_persona.yaml')"`
- 不包含真实个人信息
- 行为设计积极正向

---

## 隐私规则

- 不要提交真实聊天、导出对话、私有提示词、seed 记忆或 token
- 本地专用人格草稿保存在 `.gitignore` 的文件中
- 所有示例使用合成数据
- 人格变更属于产品行为变更，发布前需要 review

---

## English fallback

**Status: Implemented.** The YAML persona registry landed in v0.1.x. `personas/` is the source of truth.

**Quick start:** Set `PERSONA_FILE=personas/my_persona.yaml` in `.env`. Use `personas/schema.yaml` as a template. Validate with `python3 -c "from src.persona.registry import load_persona; load_persona('personas/my.yaml')"`.

**Built-in personas:** `shen_zhiwei.yaml` (default, warm/gentle senior student) and `study_buddy.yaml` (academic research assistant style).

**Contribute:** Drop a YAML file in `personas/` and open a PR. No core code changes needed.

**Privacy:** No real chats, private prompts, or user-specific memories in persona files. Use synthetic examples only.
