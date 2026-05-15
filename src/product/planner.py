from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from src.memory.models import RetrievedMemoryContext
from src.product.models import ModeState, ReplyPlan
from src.utils.time_utils import parse_iso8601


class ReplyPlanner:
    EMOTION_TOKENS = ("难受", "委屈", "焦虑", "崩溃", "低落", "烦", "慌", "累", "撑不住", "想哭", "好难")
    PRAISE_TOKENS = ("我做完了", "我完成了", "我成功了", "我过了", "我坚持住了", "我今天很棒", "我搞定了")
    STUDY_TOKENS = ("学习", "复习", "考试", "刷题", "作业", "题", "讲讲", "证明", "公式", "概念")
    PUSH_TOKENS = ("拖延", "摆烂", "不想动", "没开始", "没做", "又熬夜", "督促我", "管我")
    BOUNDARY_TOKENS = ("别这样", "不要这样", "别再", "不要再", "先别", "别逼我", "别追问")
    SEARCH_TOKENS = ("搜一下", "查一下", "帮我查", "帮我搜", "查资料", "搜索", "/search")
    SEARCH_SUPPORT_TOKENS = ("最新", "新闻", "资料", "官网", "政策", "价格", "汇率", "发布", "更新", "比赛", "比分")
    DRAW_TOKENS = ("画一张", "生成一张图", "生成图片", "生成图像", "帮我画", "帮我生成图", "绘图", "/draw")
    ANALYSIS_TOKENS = ("为什么", "分析", "解释", "怎么看", "怎么理解", "原理", "原因")
    SCENE_RULE_ORDER = (
        ("学习辅导", "study"),
        ("边界收束", "boundary"),
        ("情绪安慰", "emotion"),
        ("夸奖鼓励", "praise"),
        ("分析解释", "analysis"),
        ("轻督促", "push"),
    )

    def plan(
        self,
        *,
        user_input: str,
        memory_context: RetrievedMemoryContext,
        mode_state: ModeState,
        attachment_count: int,
    ) -> ReplyPlan:
        request_type = self._request_type(user_input)
        scene = self._scene(user_input, mode_state)
        reply_goal = self._goal(user_input, mode_state, scene)
        rhythm = self._rhythm(memory_context)
        mood = self._mood(user_input, scene)
        preferred_length = self._preferred_length(scene, request_type)
        should_search = request_type == "search"
        should_draw = request_type == "draw"
        strategy_tags = self._strategy_tags(user_input, scene, reply_goal, rhythm, attachment_count, mode_state)

        system_note_parts = [
            f"这一轮是{scene}场景。",
            f"回复目标优先放在“{reply_goal}”。",
            f"最近聊天节奏偏{rhythm}。",
        ]
        if mode_state.learning_mode:
            system_note_parts.append("学习模式已开启，解释时更像陪学和讲题。")
        if request_type == "search":
            system_note_parts.append("用户这一轮更像在要搜索型回复，整合外部资料后自然地回答，不要暴露工具痕迹。")
        if request_type == "draw":
            system_note_parts.append("用户这一轮在要绘图型回复，需要先自然接一句，再交付图片。")
        if attachment_count:
            system_note_parts.append(f"本轮带了 {attachment_count} 个附件，要自然用进去。")

        user_note_parts = [
            f"当前判断：场景={scene}，目标={reply_goal}，节奏={rhythm}，情绪={mood}。",
        ]
        if mode_state.learning_mode:
            user_note_parts.append("讲题时优先分步骤、带思路、保留人格感。")
        if scene == "情绪安慰":
            user_note_parts.append("先接住，再稳住，不要模板化安慰。")
        if scene == "夸奖鼓励":
            user_note_parts.append("夸奖要贴着他刚做到的事，不要空泛打鸡血。")
        if scene == "边界收束":
            user_note_parts.append("边界要清楚，但语气仍然是同一个人。")

        mode_text = mode_state.mode
        if mode_state.learning_mode:
            mode_text = f"{mode_text}+study"

        return ReplyPlan(
            request_type=request_type,
            scene=scene,
            reply_goal=reply_goal,
            mood=mood,
            rhythm=rhythm,
            should_search=should_search,
            should_draw=should_draw,
            learning_mode=mode_state.learning_mode,
            mode_text=mode_text,
            preferred_length=preferred_length,
            system_note=" ".join(system_note_parts),
            user_note=" ".join(user_note_parts),
            strategy_tags=strategy_tags,
        )

    def as_dict(self, plan: ReplyPlan) -> dict:
        return asdict(plan)

    def _request_type(self, user_input: str) -> str:
        text = user_input.strip()
        if self._has_explicit_draw_intent(text):
            return "draw"
        if self._has_explicit_search_intent(text):
            return "search"
        return "chat"

    def _has_explicit_search_intent(self, text: str) -> bool:
        if any(token in text for token in self.SEARCH_TOKENS):
            return True
        if "最新" in text and any(token in text for token in self.SEARCH_SUPPORT_TOKENS if token != "最新"):
            return True
        if any(token in text for token in ("查查", "搜搜")) and any(mark in text for mark in ("吗", "？", "?")):
            return True
        return False

    def _has_explicit_draw_intent(self, text: str) -> bool:
        if any(token in text for token in self.DRAW_TOKENS):
            return True
        if any(token in text for token in ("画图", "出图")) and any(token in text for token in ("帮我", "给我", "来")):
            return True
        return False

    def _scene(self, user_input: str, mode_state: ModeState) -> str:
        if mode_state.learning_mode:
            return "学习辅导"
        for scene, rule_key in self.SCENE_RULE_ORDER:
            if self._matches_scene_rule(user_input, rule_key):
                return scene
        return "日常闲聊"

    def _goal(self, user_input: str, mode_state: ModeState, scene: str) -> str:
        if scene == "情绪安慰":
            if any(token in user_input for token in ("崩溃", "撑不住", "想哭")):
                return "接住"
            return "稳住"
        if scene == "夸奖鼓励":
            return "夸奖"
        if scene == "边界收束":
            return "边界收束"
        if scene == "分析解释":
            return "解释"
        if scene == "学习辅导":
            if any(token in user_input for token in self.PUSH_TOKENS):
                return "督促"
            return "解释"
        if any(token in user_input for token in self.PUSH_TOKENS):
            return "轻压"
        if mode_state.learning_mode:
            return "督促"
        return "陪伴"

    def _mood(self, user_input: str, scene: str) -> str:
        if scene == "情绪安慰":
            return "脆弱"
        if scene == "夸奖鼓励":
            return "积极"
        if scene == "学习辅导":
            return "专注"
        if any(token in user_input for token in self.PUSH_TOKENS):
            return "拖延"
        return "平稳"

    def _preferred_length(self, scene: str, request_type: str) -> str:
        if request_type == "search":
            return "medium_structured"
        if request_type == "draw":
            return "short"
        if scene == "学习辅导":
            return "medium_structured"
        if scene in {"情绪安慰", "日常闲聊"}:
            return "medium"
        return "short_to_medium"

    def _rhythm(self, memory_context: RetrievedMemoryContext) -> str:
        if len(memory_context.recent_messages) < 2:
            return "稀疏"
        recent = memory_context.recent_messages[-4:]
        timestamps = [parse_iso8601(message.created_at) for message in recent]
        timestamps = [item for item in timestamps if item is not None]
        if len(timestamps) < 2:
            return "平稳"
        spans = [
            (timestamps[index + 1] - timestamps[index]).total_seconds()
            for index in range(len(timestamps) - 1)
        ]
        average_gap = sum(spans) / len(spans)
        if average_gap <= 300:
            return "密集"
        if average_gap >= 43200:
            return "稀疏"
        return "平稳"

    def _strategy_tags(
        self,
        user_input: str,
        scene: str,
        reply_goal: str,
        rhythm: str,
        attachment_count: int,
        mode_state: ModeState,
    ) -> list[str]:
        tags = [scene, reply_goal, rhythm]
        if attachment_count:
            tags.append("multimodal")
        if mode_state.learning_mode:
            tags.append("study_mode")
        if any(token in user_input for token in ("今天", "刚刚", "终于", "总算")):
            tags.append("fresh_state")
        return tags

    def _matches_scene_rule(self, text: str, rule_key: str) -> bool:
        if rule_key == "study":
            return self._contains_any(text, self.STUDY_TOKENS)
        if rule_key == "boundary":
            return self._contains_any(text, self.BOUNDARY_TOKENS)
        if rule_key == "emotion":
            return self._contains_any(text, self.EMOTION_TOKENS)
        if rule_key == "praise":
            return self._contains_any(text, self.PRAISE_TOKENS)
        if rule_key == "analysis":
            return self._contains_any(text, self.ANALYSIS_TOKENS)
        if rule_key == "push":
            return self._contains_any(text, self.PUSH_TOKENS)
        return False

    def _contains_any(self, text: str, tokens: tuple[str, ...]) -> bool:
        return any(token in text for token in tokens)
