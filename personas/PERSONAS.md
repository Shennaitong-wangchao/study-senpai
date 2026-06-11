# Persona Gallery / 人格画廊

本目录收录 Study Senpai 内置和社区贡献的人格 YAML 文件。

---

## 如何使用

```bash
# 设置环境变量切换人格
PERSONA_FILE=personas/english_coach.yaml

# 或者在 .env 文件中设置
echo "PERSONA_FILE=personas/english_coach.yaml" >> .env
```

验证人格加载：

```bash
python3 -c "from src.persona.registry import load_persona; p = load_persona('personas/english_coach.yaml'); print('✓', p.name)"
```

---

## 内置人格

### 沈知微（默认）
**文件：** `personas/shen_zhiwei.yaml`

温柔克制的高三学姐。聪明、稳定，对你是明确的例外——会多管一点，多问一句，替你收状态。

**适合：** 高中生、需要稳定学习陪伴的用户。

---

### 林晓研（学术助手）
**文件：** `personas/study_buddy.yaml`

研究生学姐，学术严谨、逻辑清晰。善于用框架分析问题，推荐使用费曼学习法、SQ3R 等高效方法。

**适合：** 大学生、研究生、需要方法论指导的用户。

---

### Alex（英语教练）
**文件：** `personas/english_coach.yaml`

耐心风趣的英语口语教练，中英双语交流。在对话中自然融入英文短句练习，纠正语法轻而不伤面子。

**适合：** 正在学习英语口语的用户。

---

### 林程远（代码导师）
**文件：** `personas/code_mentor.yaml`

五年经验的全栈开发者，务实犀利。不直接给答案，用类比和例子引导你思考，会主动 code review。

**适合：** 编程学习者、想要有人监督项目进度的开发者。

---

### 史云飞教授（历史老师）
**文件：** `personas/history_teacher.yaml`

博学幽默的历史系教授，用故事讲历史。会把历史事件联系到现代，提出反事实讨论激发思考。

**适合：** 历史爱好者、备考历史的学生。

---

### 何悠悠（健康伙伴）
**文件：** `personas/wellness_buddy.yaml`

温暖细腻的健康生活伙伴。会主动询问睡眠、饮食、运动状况，给具体可操作的减压建议。

**适合：** 生活节奏快、需要关注身心健康的用户。

---

## 贡献你的人格

欢迎向仓库提交 PR 添加新人格！

### 步骤

1. 参考 `personas/schema.yaml` 了解所有字段含义
2. 复制 `personas/shen_zhiwei.yaml` 作为起点
3. 修改各字段，创建你的人格
4. 本地验证：
   ```bash
   python3 -c "from src.persona.registry import load_persona; load_persona('personas/your_persona.yaml'); print('OK')"
   ```
5. 提交 PR，使用 [人格贡献模板](.github/ISSUE_TEMPLATE/persona_contribution.md)

### 规则

- **不要** 包含真实个人信息（真实姓名、学校、地址）
- 行为设计符合正向价值观
- 所有字段必填（15 个），缺一不可
- 使用有意义的文件名（如 `physics_tutor.yaml`、`debate_coach.yaml`）

### 人格创意方向

- 理科家教（物理、化学、生物）
- 语文/写作老师
- 职业规划顾问
- 运动/健身教练
- 音乐理论老师
- 哲学讨论伙伴
- 面试准备教练

---

## English fallback

This directory contains built-in and community-contributed persona YAML files for Study Senpai.

**Quick start:** Set `PERSONA_FILE=personas/english_coach.yaml` in `.env` to switch personas. Validate with `python3 -c "from src.persona.registry import load_persona; load_persona('personas/my.yaml')"`.

**Contribute:** Copy any YAML as a starting point, fill all 15 required fields, validate, and open a PR. No code changes needed — just the YAML file.

See [docs/PERSONA_SYSTEM_PUBLIC.md](../docs/PERSONA_SYSTEM_PUBLIC.md) for the full registry design.
