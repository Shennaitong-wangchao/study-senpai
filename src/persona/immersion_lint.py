from __future__ import annotations

import re

from src.utils.text_utils import compact_text


PARENTHETICAL_BLOCKLIST_TOKENS = (
    "心里",
    "脑子",
    "想到",
    "想着",
    "觉得",
    "意识到",
    "明白",
    "系统",
    "提示词",
    "工具",
    "AI",
    "模型",
)

STAGE_PAREN_RE = re.compile(r"[（(]([^（）()\n]{2,90})[）)]")

FIRST_PERSON_REPLACEMENTS = (
    ("我刚才这边停了一下", "我刚才停了一下"),
    ("我刚才这边", "我刚才"),
    ("她说话会压轻一点", "我会把声音放轻一点"),
    ("她这边", "我这边"),
    ("她把", "我把"),
    ("她在", "我在"),
    ("她从", "我从"),
    ("她吃", "我吃"),
    ("她声音", "我声音"),
    ("她整个人", "我整个人"),
    ("像怕惊动已经困了的人", "怕吵到你"),
    ("然后脑子里就很自然地绕到你那里去了", "然后我就又想到你了"),
    ("脑子里就很自然地绕到你那里去了", "我就又想到你了"),
    ("沈知微承诺成为用户最稳固的后方和确定感", "我会稳稳站在你这边"),
    ("用户最稳固的后方和确定感", "你可以靠一下的地方"),
)


def repair_immersive_voice(text: str) -> str:
    """Keep companion chat in first-person voice while preserving short action beats."""
    updated = normalize_stage_parentheticals(text)
    for old, new in FIRST_PERSON_REPLACEMENTS:
        updated = updated.replace(old, new)
    updated = normalize_stage_parentheticals(updated)
    updated = re.sub(r"。{2,}", "。", updated)
    updated = re.sub(r"\s+([，。！？；：])", r"\1", updated)
    updated = re.sub(r"([，。！？；：])\s+", r"\1", updated)
    updated = re.sub(r"\n{3,}", "\n\n", updated)
    return updated.strip()


def strip_stage_parentheticals(text: str) -> str:
    return normalize_stage_parentheticals(text)


def normalize_stage_parentheticals(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        content = compact_text(match.group(1))
        if any(token in content for token in PARENTHETICAL_BLOCKLIST_TOKENS):
            return ""
        content = _first_person_parenthetical(content)
        return f"（{content}）"

    updated = STAGE_PAREN_RE.sub(replace, text)
    updated = re.sub(r"(?m)^\s+$", "", updated)
    updated = re.sub(r"\n{3,}", "\n\n", updated)
    return updated.strip()


def _first_person_parenthetical(content: str) -> str:
    updated = content.strip()
    updated = updated.replace("沈知微的", "我的")
    updated = updated.replace("沈知微", "我")
    updated = updated.replace("她的", "我的")
    for old, new in FIRST_PERSON_REPLACEMENTS:
        updated = updated.replace(old, new)
    updated = re.sub(r"^她(?=[把在从吃声整看抬垂停轻伸坐站靠转回拿放])", "我", updated)
    return updated.strip()
