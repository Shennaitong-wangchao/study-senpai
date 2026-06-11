---
name: 人格贡献 / Persona contribution
about: 贡献一个新的 AI 人格 YAML 文件 / Contribute a new AI persona YAML file
title: "[Persona]: "
labels: persona
assignees: ""
---

## 人格简介 / Persona description

简短描述这个人格的特点和定位。

Brief description of this persona's characteristics and use case.

## YAML 预览 / YAML preview

```yaml
name: 
age: 
school_role: 
public_title: 
core_identity: |
  
tone: 
language: 
```

## 使用场景 / Target use case

这个人格最适合哪种学习或陪伴需求？

What learning or companionship need does this persona serve best?

## 安全检查 / Safety checklist

- [ ] 人格定义中不包含任何真实个人信息
- [ ] 行为设计符合正向价值观
- [ ] 已通过本地测试（`PERSONA_FILE=personas/my_persona.yaml python3 -m src.main`）
- [ ] YAML 格式通过校验（`python3 -c "from src.persona.registry import load_persona; load_persona('personas/my_persona.yaml')"`)
