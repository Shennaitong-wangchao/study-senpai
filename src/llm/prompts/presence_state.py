from __future__ import annotations

from typing import Any

from src.utils.json_utils import json_dumps
from src.utils.text_utils import truncate_text


PRESENCE_STATE_SYSTEM_PROMPT = """你是陪伴 bot 的 presence state classifier。
你只负责把最近对话转成保守的状态判断，不负责聊天。

必须遵守：
1. 输出 JSON object，不要附带解释文本。
2. 睡眠判断要保守：不能只因为深夜、用户不回复或说“困了”就判定 asleep。
3. 只有用户明确表达“去睡/睡了/晚安/准备睡/我先睡”等才可给 asleep。
4. “睡不着/失眠/没睡着/醒了/起床/任何新的用户回复”优先表示 awake 或 probably_awake。
5. 如果用户情绪脆弱、焦虑、崩溃、边界收束，助手情绪必须压低，先照顾用户。

JSON schema:
{
  "sleep_state": "unknown|awake|asleep|probably_awake|probably_asleep",
  "sleep_confidence": 0.0,
  "sleep_reason": "string",
  "sleep_evidence": [{"source":"message|time|history","signal":"string","weight":0.0}],
  "expires_in_minutes": 0,
  "assistant_emotion_delta": {
    "longing": 0.0,
    "hurt": 0.0,
    "tenderness": 0.0,
    "worry": 0.0,
    "jealousy": 0.0,
    "caution": 0.0
  },
  "assistant_mood_label": "string",
  "safety_note": "string"
}"""


def build_presence_state_user_prompt(
    *,
    current_state: dict[str, Any],
    latest_user_text: str,
    recent_messages: list[dict[str, str]],
    local_time: str,
) -> str:
    payload = {
        "local_time": local_time,
        "latest_user_text": truncate_text(latest_user_text, 500),
        "current_state": current_state,
        "recent_messages": recent_messages[-8:],
    }
    return (
        "请根据以下信息更新 presence state。保持保守，尤其是睡眠状态。\n"
        f"{json_dumps(payload)}"
    )
