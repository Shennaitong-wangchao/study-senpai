"""
Persona YAML 注册表模块

提供从 YAML 文件加载 PersonaProfile 的功能，支持：
- 从任意路径加载单个 YAML 人格文件
- 加载默认人格（personas/shen_zhiwei.yaml）
- 列出可用的 YAML 人格文件
- 完整的字段校验，缺失字段时给出清晰的错误提示

依赖：仅需 PyYAML（pyyaml），不引入其他第三方库。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from src.persona.profile import PersonaProfile

logger = logging.getLogger(__name__)

# PersonaProfile 需要的所有字段（与 dataclass 字段顺序一致）
_REQUIRED_FIELDS: tuple[str, ...] = (
    "name",
    "age",
    "school_role",
    "public_title",
    "core_identity",
    "outward_presence",
    "user_exception",
    "relationship_position",
    "tone",
    "emotional_method",
    "addressing_policy",
    "action_policy",
    "relationship_goal",
    "memory_goal",
    "language",
)

# 默认 personas 目录（相对于项目根目录）
_DEFAULT_PERSONAS_DIR = Path(__file__).resolve().parent.parent.parent / "personas"

# 默认人格文件路径
_DEFAULT_PERSONA_FILE = _DEFAULT_PERSONAS_DIR / "shen_zhiwei.yaml"


class PersonaLoadError(Exception):
    """人格 YAML 加载失败时抛出的异常"""


def _validate_and_build(data: dict[str, Any], source_path: str) -> PersonaProfile:
    """
    校验 YAML 数据字段完整性，并构建 PersonaProfile 实例。

    :param data: 从 YAML 解析得到的字典
    :param source_path: 来源文件路径（仅用于错误提示）
    :raises PersonaLoadError: 当字段缺失、类型错误或数据无效时
    :returns: 校验通过的 PersonaProfile 实例
    """
    # 检查缺失字段
    missing = [field for field in _REQUIRED_FIELDS if field not in data]
    if missing:
        raise PersonaLoadError(
            f"人格文件 '{source_path}' 缺少必填字段：{missing}\n"
            f"所有必填字段：{list(_REQUIRED_FIELDS)}\n"
            f"请参考 personas/schema.yaml 补全缺失字段。"
        )

    # 校验 age 必须是正整数
    age_raw = data["age"]
    if not isinstance(age_raw, int) or age_raw <= 0:
        raise PersonaLoadError(
            f"人格文件 '{source_path}' 中 'age' 字段必须是正整数，"
            f"当前值为：{age_raw!r}（类型：{type(age_raw).__name__}）"
        )

    # 校验所有字符串字段不为空（去除首尾空白后）
    string_fields = [f for f in _REQUIRED_FIELDS if f != "age"]
    for field in string_fields:
        value = data[field]
        if not isinstance(value, str):
            raise PersonaLoadError(
                f"人格文件 '{source_path}' 中 '{field}' 字段必须是字符串，"
                f"当前类型为：{type(value).__name__}"
            )
        if not value.strip():
            raise PersonaLoadError(
                f"人格文件 '{source_path}' 中 '{field}' 字段不能为空字符串。"
            )

    return PersonaProfile(
        name=data["name"].strip(),
        age=data["age"],
        school_role=data["school_role"].strip(),
        public_title=data["public_title"].strip(),
        core_identity=data["core_identity"].strip(),
        outward_presence=data["outward_presence"].strip(),
        user_exception=data["user_exception"].strip(),
        relationship_position=data["relationship_position"].strip(),
        tone=data["tone"].strip(),
        emotional_method=data["emotional_method"].strip(),
        addressing_policy=data["addressing_policy"].strip(),
        action_policy=data["action_policy"].strip(),
        relationship_goal=data["relationship_goal"].strip(),
        memory_goal=data["memory_goal"].strip(),
        language=data["language"].strip(),
    )


def load_persona(path: str | Path) -> PersonaProfile:
    """
    从指定 YAML 文件加载 PersonaProfile。

    :param path: YAML 文件路径（str 或 Path）
    :raises PersonaLoadError: 当文件不存在、YAML 格式错误或字段缺失时
    :returns: 加载并校验成功的 PersonaProfile 实例
    """
    file_path = Path(path)
    if not file_path.exists():
        raise PersonaLoadError(f"人格文件不存在：'{file_path}'")
    if not file_path.is_file():
        raise PersonaLoadError(f"指定路径不是文件：'{file_path}'")

    try:
        # 强制使用 UTF-8 编码，支持中文内容
        raw_text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PersonaLoadError(f"无法读取人格文件 '{file_path}'：{exc}") from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise PersonaLoadError(
            f"人格文件 '{file_path}' YAML 格式解析失败：{exc}"
        ) from exc

    if not isinstance(data, dict):
        raise PersonaLoadError(
            f"人格文件 '{file_path}' 顶层结构必须是 YAML 映射（key: value），"
            f"当前类型为：{type(data).__name__}"
        )

    persona = _validate_and_build(data, str(file_path))
    logger.debug("从 '%s' 成功加载人格：%s", file_path, persona.name)
    return persona


def load_default_persona() -> PersonaProfile:
    """
    加载默认人格 personas/shen_zhiwei.yaml。

    :raises PersonaLoadError: 当默认人格文件不存在或格式错误时
    :returns: 沈知微人格的 PersonaProfile 实例
    """
    return load_persona(_DEFAULT_PERSONA_FILE)


def list_available_personas(personas_dir: str | Path | None = None) -> list[str]:
    """
    列出指定目录（默认为 personas/）下所有可用的 YAML 人格文件。

    仅返回 .yaml 和 .yml 扩展名的文件，schema.yaml 会被包含在内（供参考），
    调用方可自行过滤。

    :param personas_dir: 要扫描的目录，None 时使用默认 personas/ 目录
    :returns: 文件名列表（不含目录路径），按字母顺序排序
    """
    target_dir = Path(personas_dir) if personas_dir is not None else _DEFAULT_PERSONAS_DIR

    if not target_dir.exists():
        logger.warning("personas 目录不存在：%s", target_dir)
        return []

    if not target_dir.is_dir():
        logger.warning("指定路径不是目录：%s", target_dir)
        return []

    # 收集所有 .yaml 和 .yml 文件，按名称排序
    yaml_files = sorted(
        f.name
        for f in target_dir.iterdir()
        if f.is_file() and f.suffix.lower() in {".yaml", ".yml"}
    )
    return yaml_files
