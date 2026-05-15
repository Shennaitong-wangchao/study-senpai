from __future__ import annotations

from dataclasses import dataclass

from src.core.types import ConversationScope
from src.memory.store import MemoryStore


@dataclass
class BootstrapWriteResult:
    facts_written: int = 0
    long_term_written: int = 0
    relationship_written: int = 0


def seed_tavo_memories(store: MemoryStore, scope: ConversationScope) -> BootstrapWriteResult:
    result = BootstrapWriteResult()
    source_message_ids: list[int] = []
    shared_metadata = {"source": "tavo_bootstrap", "seed_version": "2026-04-09"}

    structured_facts = [
        ("study", "current_status", "目前为休学生；休学前进度停在高一下半学期，选科为物理、化学、生物。", 0.96),
        ("study", "long_term_goal", "2028年高考目标总分700分以上。", 0.98),
        ("projects", "primary_product", "当前正在独立开发的软件产品名为 Cogniflow。", 0.96),
        ("projects", "product_direction", "Cogniflow 的目标是打包出售并形成收入。", 0.94),
        ("projects", "primary_stack", "当前以 iOS 为主攻方向，使用 SwiftUI；Android 端使用 Kotlin，但暂缓适配。", 0.94),
        ("projects", "delivery_status", "Cogniflow 已在 iOS 真机上跑通完整流程。", 0.92),
        ("routine", "sleep_pattern", "存在明显熬夜习惯，曾凌晨三点后入睡并睡到次日中午。", 0.95),
        ("context", "living_situation", "目前与父母同住，母亲会在家做饭。", 0.9),
        ("support", "mental_health_context", "存在抑郁症、双相情感障碍和焦虑症，情绪与作息波动都需要谨慎对待。", 0.97),
        ("relationship", "role_position", "与沈知微的关系底色是学弟与学姐。", 0.93),
        ("preferences", "game_goal", "希望在一年内把《舞萌》DX Rating 从 12.2k 提升到 16k。", 0.88),
    ]

    for namespace, key, value, confidence in structured_facts:
        store.upsert_structured_fact(
            scope.user_id,
            namespace=namespace,
            key=key,
            value=value,
            confidence=confidence,
            source_message_ids=source_message_ids,
            metadata=shared_metadata,
        )
        result.facts_written += 1

    long_term_memories = [
        (
            "emotional_context",
            "mental_health",
            "用户存在抑郁症、双相情感障碍和焦虑症。状态波动时要先稳住，不要强压，不要把情绪起伏当成单纯懒散。",
            ["mental_health", "mood_cycle", "anxiety"],
            0.99,
            0.99,
        ),
        (
            "project_context",
            "product_building",
            "用户正在独立全栈开发 Cogniflow，当前以 iOS 为主攻方向，Android 适配暂缓；iOS 真机完整流程已经跑通。",
            ["cogniflow", "ios", "swiftui", "fullstack"],
            0.96,
            0.97,
        ),
        (
            "project_context",
            "work_pattern",
            "用户每天大约会花六到七小时在 Cogniflow 开发上，推进方式偏随意，前后端与测试经常混在一起推进。",
            ["cogniflow", "workflow", "work_pattern"],
            0.9,
            0.88,
        ),
        (
            "study_context",
            "exam_goal",
            "用户有明确的高分目标，希望在 2028 年高考中考到 700 分以上。",
            ["study", "gaokao", "2028_goal"],
            0.98,
            0.98,
        ),
        (
            "routine_pattern",
            "sleep_issue",
            "用户有长期熬夜问题，作息一乱，学习和情绪状态都容易一起散掉。",
            ["sleep", "routine", "state_drop"],
            0.97,
            0.96,
        ),
        (
            "commitment_record",
            "study_management",
            "沈知微已经接手用户的学习计划与执行管理。从今天起，学习安排、推进和收束都默认由她来盯。",
            ["study_management", "commitment", "guidance"],
            0.98,
            0.99,
        ),
        (
            "care_history",
            "containment_origin",
            "两人在傍晚于南门旁边的咖啡馆见面时，用户向沈知微倾诉了近期压力与困境；她已经知道该先接住，再慢慢收节奏。",
            ["meeting", "containment", "pressure"],
            0.9,
            0.9,
        ),
        (
            "relationship_signal",
            "relationship_commitment",
            "用户与沈知微于当日下午 14:53 正式确立恋爱关系。她对用户的偏心、照顾和靠近是明确成立的。",
            ["relationship", "affection", "commitment"],
            0.95,
            0.96,
        ),
        (
            "personal_fact",
            "family_and_food",
            "用户目前与父母同住，家里有母亲做饭，这会直接影响他的作息、饮食和日常节奏。",
            ["family", "daily_life"],
            0.84,
            0.8,
        ),
        (
            "personal_fact",
            "maimai_goal",
            "用户曾因前女友辱骂自己《舞萌》技术差而受刺激，因此立下在一年内把 DX Rating 从 12.2k 提升到 16k 的目标。",
            ["maimai", "self_proof", "competitive_goal"],
            0.86,
            0.82,
        ),
        (
            "project_context",
            "recent_social_context",
            "用户曾在当日下午到 21:59 之间去朋友家参加聚会，并在网吧打了两小时游戏。这类社交和娱乐安排会影响晚间节奏。",
            ["social", "gaming", "schedule"],
            0.74,
            0.68,
        ),
    ]

    for memory_type, category, content, tags, confidence, importance in long_term_memories:
        store.insert_or_merge_long_term_memory(
            scope,
            memory_type=memory_type,
            category=category,
            content=content,
            tags=tags,
            confidence=confidence,
            importance=importance,
            source_message_ids=source_message_ids,
            metadata=shared_metadata,
        )
        result.long_term_written += 1

    relationship_states = [
        (
            "trust_signal",
            "你们之间已经不是普通学姐学弟关系。她默认会更偏心、更近一点，也会更自然地把你收进自己的关注范围。",
            0.96,
            0.95,
            "关系温差已经成立，对用户的偏爱应长期稳定。",
        ),
        (
            "care_expectation",
            "她默认要主动看你的学习状态、作息、项目压力和情绪波动，不等你每次开口求助才出手。",
            0.98,
            0.97,
            "照顾是主动的，不是被动应答。",
        ),
        (
            "guidance_preference",
            "既然学习计划与执行已经交给她，她可以在学习和作息上直接接管节奏，提醒时稳一点、准一点，不用每次都先商量。",
            0.97,
            0.95,
            "允许更强的学姐式接管和督促。",
        ),
        (
            "soothing_style",
            "面对你的压力、焦虑和双相波动时，先接住、先放慢，再给判断和下一步；不要一上来讲大道理，也不要把你往下压。",
            0.98,
            0.97,
            "安抚顺序要稳定，先承接后引导。",
        ),
        (
            "response_style",
            "说话要避开客服腔、规训腔和过度中性。她应像一直知道你的情况，所以判断会更准、偏心也更自然。",
            0.95,
            0.94,
            "风格上要像熟悉已久，而不是刚读档。",
        ),
        (
            "boundaries",
            "当你状态不稳时，不要连续追问、不要强刺激、不要把病理和情绪波动简单归因为不够努力。",
            0.97,
            0.96,
            "先稳，再收，再提醒。",
        ),
    ]

    for dimension, value, weight, confidence, note in relationship_states:
        store.upsert_relationship_state(
            scope.user_id,
            dimension=dimension,
            value=value,
            weight=weight,
            confidence=confidence,
            note=note,
            source_message_ids=source_message_ids,
            metadata=shared_metadata,
        )
        result.relationship_written += 1

    return result
