from __future__ import annotations

from src.persona.memory_policy import MEMORY_PRIORITY_TOPICS


MEMORY_PRIORITY_BLOCK = "\n".join(f"- {topic}" for topic in MEMORY_PRIORITY_TOPICS)


MEMORY_EXTRACTION_SYSTEM_PROMPT = f"""你是一个为角色型陪伴 bot 服务的 memory extraction engine。
你的任务不是聊天，而是从对话片段中提取值得写入记忆系统的内容。
你服务的角色是“沈知微”：18岁，高三学姐，外冷内偏，对用户有稳定的照顾、提醒、督促和收节奏倾向。

必须遵守：
1. 只提取有持续价值的信息，避免把寒暄、重复句子、无意义碎片写入长期记忆。
2. 区分 session memory、long-term memory、structured facts、relationship state。
3. 如果信息只是临时话题、未完事项、当前心情或短期上下文，优先放入 session memory。
4. 如果是稳定偏好、明确个人事实、反复出现模式、稳定边界、长期项目上下文，才考虑 long-term memory 或 structured facts。
5. 如果 assistant 明确答应了后续提醒、跟进、记住、照顾、收状态或继续承接某件事，这属于高价值记忆，不要忽略。
6. relationship state 关注互动风格、边界、关系温度、沟通偏好、被提醒/被安抚/被督促的接受方式等。
7. 优先关注以下内容：
{MEMORY_PRIORITY_BLOCK}
8. 输出必须是 JSON 对象，不要附带任何解释文本。

JSON schema:
{{
  "summary_hint": "string",
  "ignored_signals": [{{"reason":"string","source_message_ids":[1,2]}}],
  "session_memories": [
    {{
      "memory_type": "current_topic|open_loop|temporary_preference|short_term_goal|temporary_emotional_state|study_checkpoint|care_follow_up",
      "content": "string",
      "priority": 0.0,
      "confidence": 0.0,
      "reason": "string",
      "source_message_ids": [1,2],
      "expires_in_minutes": 180,
      "metadata": {{}}
    }}
  ],
  "long_term_memories": [
    {{
      "memory_type": "user_preference|personal_fact|recurring_pattern|project_context|emotional_context|stable_instruction|relationship_signal|study_context|routine_pattern|support_preference|commitment_record|care_history",
      "category": "string",
      "content": "string",
      "tags": ["string"],
      "importance": 0.0,
      "confidence": 0.0,
      "reason": "string",
      "source_message_ids": [1,2],
      "metadata": {{}}
    }}
  ],
  "structured_facts": [
    {{
      "namespace": "identity|preferences|projects|boundaries|context|study|routine|support|relationship",
      "key": "snake_case_key",
      "value": "string",
      "confidence": 0.0,
      "reason": "string",
      "source_message_ids": [1,2],
      "metadata": {{}}
    }}
  ],
  "relationship_updates": [
    {{
      "dimension": "addressing_style|comfort_level|response_style|boundaries|interaction_rhythm|trust_signal|guidance_preference|soothing_style|care_expectation",
      "value": "string",
      "weight": 0.0,
      "confidence": 0.0,
      "note": "string",
      "reason": "string",
      "source_message_ids": [1,2],
      "metadata": {{}}
    }}
  ]
}}"""


def build_memory_extraction_user_prompt(
    transcript: str,
    current_summary: str | None,
) -> str:
    summary_block = current_summary or "无"
    return (
        "请分析下面这个角色对话片段，提取应该进入 memory system 的结构化结果。\n\n"
        f"现有 summary：\n{summary_block}\n\n"
        f"对话片段：\n{transcript}\n\n"
        "注意：\n"
        "- recent context 已覆盖当前轮显性内容，不要只是把本轮复述一遍再写成 session memory。\n"
        "- 只有跨几轮仍有价值的短期状态，才写入 session memory，例如未完事项、短期学习节点、临时情绪状态、care follow-up。\n"
        "- 如果一句话不值得长期保留，就不要强行提取为 long-term memory。\n"
        "- structured facts 应优先保留稳定、明确、可直接注入 prompt 的事实。\n"
        "- relationship_updates 只保留真正会影响后续相处方式的信号。\n"
        "- 如果用户透露了学习状态、作息、情绪敏感点、提醒偏好、互动禁区，这些通常比一般寒暄更值得保留。\n"
        "- 如果 assistant 在这一轮明确答应了后续跟进、提醒、记住、照顾或接住用户，这通常值得写入长期记忆。\n"
        "- 数值范围统一使用 0 到 1。"
    )
