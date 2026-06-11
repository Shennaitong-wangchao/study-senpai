"""
测试 Persona YAML 注册表模块 (src/persona/registry.py)

覆盖范围：
- 加载合法 YAML 人格文件（shen_zhiwei.yaml / study_buddy.yaml）
- 字段校验：缺失字段、类型错误、空字符串
- list_available_personas：空目录、正常目录、自定义目录
- 环境变量 PERSONA_FILE 覆盖：有效文件、无效文件、未设置
- load_default_persona：正常路径、文件不存在时的错误
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from src.persona.profile import PersonaProfile, SHEN_ZHIWEI_PROFILE
from src.persona.registry import (
    PersonaLoadError,
    load_default_persona,
    load_persona,
    list_available_personas,
    _DEFAULT_PERSONAS_DIR,
    _DEFAULT_PERSONA_FILE,
)


# ─────────────────────────────────────────────────────────────
# 测试辅助：构造最小有效 YAML 内容
# ─────────────────────────────────────────────────────────────

def _minimal_valid_yaml() -> dict:
    """返回通过所有校验的最小人格字段集合"""
    return {
        "name": "测试人格",
        "age": 20,
        "school_role": "大一学姐",
        "public_title": "测试人格定位",
        "core_identity": "这是一个测试人格的核心身份描述。",
        "outward_presence": "对外表现描述",
        "user_exception": "对用户的例外描述",
        "relationship_position": "关系定位描述",
        "tone": "语气描述",
        "emotional_method": "情绪处理方法",
        "addressing_policy": "称呼策略",
        "action_policy": "动作策略",
        "relationship_goal": "关系目标",
        "memory_goal": "记忆目标",
        "language": "默认中文",
    }


def _write_yaml(tmp_path: Path, data: dict, filename: str = "test_persona.yaml") -> Path:
    """将字典写为 YAML 文件并返回路径"""
    file = tmp_path / filename
    file.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return file


# ─────────────────────────────────────────────────────────────
# load_persona — 正常加载
# ─────────────────────────────────────────────────────────────

class TestLoadPersona:
    def test_load_valid_yaml_returns_persona_profile(self, tmp_path: Path) -> None:
        """合法 YAML 文件应成功加载并返回 PersonaProfile 实例"""
        data = _minimal_valid_yaml()
        file = _write_yaml(tmp_path, data)
        persona = load_persona(file)

        assert isinstance(persona, PersonaProfile)
        assert persona.name == "测试人格"
        assert persona.age == 20
        assert persona.school_role == "大一学姐"
        assert persona.language == "默认中文"

    def test_load_strips_surrounding_whitespace_in_strings(self, tmp_path: Path) -> None:
        """字符串字段的首尾空白应被去除"""
        data = _minimal_valid_yaml()
        data["name"] = "  空白学姐  "
        data["school_role"] = "\n高三\n"
        file = _write_yaml(tmp_path, data)
        persona = load_persona(file)

        assert persona.name == "空白学姐"
        assert persona.school_role == "高三"

    def test_load_accepts_str_and_path_types(self, tmp_path: Path) -> None:
        """path 参数接受 str 和 Path 两种类型"""
        file = _write_yaml(tmp_path, _minimal_valid_yaml())

        persona_via_str = load_persona(str(file))
        persona_via_path = load_persona(file)

        assert persona_via_str.name == persona_via_path.name

    def test_load_supports_multiline_yaml_block_scalar(self, tmp_path: Path) -> None:
        """YAML 块标量（|）的多行字符串应被正确加载"""
        yaml_content = """\
name: "林晓研"
age: 22
school_role: "研究生"
public_title: "测试"
core_identity: |
  第一行身份描述
  第二行补充内容
outward_presence: "对外表现"
user_exception: "用户例外"
relationship_position: "关系定位"
tone: "语气"
emotional_method: "情绪方法"
addressing_policy: "称呼策略"
action_policy: "动作策略"
relationship_goal: "关系目标"
memory_goal: "记忆目标"
language: "中文"
"""
        file = tmp_path / "multiline.yaml"
        file.write_text(yaml_content, encoding="utf-8")
        persona = load_persona(file)

        assert persona.name == "林晓研"
        assert "第一行" in persona.core_identity
        assert "第二行" in persona.core_identity

    def test_load_shen_zhiwei_yaml_matches_inline_profile(self) -> None:
        """从 YAML 加载的沈知微人格应与 Python 内联定义完全一致"""
        yaml_persona = load_persona(_DEFAULT_PERSONA_FILE)

        assert yaml_persona.name == SHEN_ZHIWEI_PROFILE.name
        assert yaml_persona.age == SHEN_ZHIWEI_PROFILE.age
        assert yaml_persona.school_role == SHEN_ZHIWEI_PROFILE.school_role
        assert yaml_persona.public_title == SHEN_ZHIWEI_PROFILE.public_title
        # 核心字段比较：
        # Python 内联定义用字符串拼接（无换行），YAML 块标量会保留换行符。
        # 去掉空白字符后的内容应完全一致。
        def _normalize(s: str) -> str:
            return "".join(s.split())

        assert _normalize(yaml_persona.core_identity) == _normalize(SHEN_ZHIWEI_PROFILE.core_identity)
        assert yaml_persona.language == SHEN_ZHIWEI_PROFILE.language

    def test_load_study_buddy_yaml_returns_different_persona(self) -> None:
        """study_buddy.yaml 应加载不同于沈知微的独立人格"""
        study_buddy = load_persona(_DEFAULT_PERSONAS_DIR / "study_buddy.yaml")

        assert isinstance(study_buddy, PersonaProfile)
        assert study_buddy.name != SHEN_ZHIWEI_PROFILE.name
        assert study_buddy.age == 22


# ─────────────────────────────────────────────────────────────
# load_persona — 错误处理
# ─────────────────────────────────────────────────────────────

class TestLoadPersonaErrors:
    def test_raises_when_file_not_found(self, tmp_path: Path) -> None:
        """文件不存在时应抛出 PersonaLoadError"""
        with pytest.raises(PersonaLoadError, match="不存在"):
            load_persona(tmp_path / "ghost.yaml")

    def test_raises_when_path_is_directory(self, tmp_path: Path) -> None:
        """指定路径是目录时应抛出 PersonaLoadError"""
        with pytest.raises(PersonaLoadError, match="不是文件"):
            load_persona(tmp_path)

    def test_raises_on_invalid_yaml_syntax(self, tmp_path: Path) -> None:
        """YAML 语法错误时应抛出 PersonaLoadError，提示解析失败"""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("name: [unclosed", encoding="utf-8")
        with pytest.raises(PersonaLoadError, match="解析失败"):
            load_persona(bad_file)

    def test_raises_when_top_level_is_not_dict(self, tmp_path: Path) -> None:
        """顶层结构不是映射时应抛出 PersonaLoadError"""
        file = tmp_path / "list.yaml"
        file.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(PersonaLoadError, match="映射"):
            load_persona(file)

    @pytest.mark.parametrize("missing_field", [
        "name", "age", "school_role", "core_identity",
        "tone", "relationship_goal", "language",
    ])
    def test_raises_on_missing_required_field(self, tmp_path: Path, missing_field: str) -> None:
        """缺少任意必填字段时应抛出 PersonaLoadError，并在消息中指明缺失字段"""
        data = _minimal_valid_yaml()
        del data[missing_field]
        file = _write_yaml(tmp_path, data)

        with pytest.raises(PersonaLoadError, match=missing_field):
            load_persona(file)

    def test_error_message_lists_all_missing_fields(self, tmp_path: Path) -> None:
        """多个字段缺失时，错误消息应列出所有缺失字段"""
        data = _minimal_valid_yaml()
        del data["name"]
        del data["age"]
        del data["language"]
        file = _write_yaml(tmp_path, data)

        with pytest.raises(PersonaLoadError) as exc_info:
            load_persona(file)
        msg = str(exc_info.value)
        assert "name" in msg
        assert "age" in msg
        assert "language" in msg

    def test_raises_when_age_is_string(self, tmp_path: Path) -> None:
        """age 字段为字符串时应抛出 PersonaLoadError"""
        data = _minimal_valid_yaml()
        data["age"] = "二十岁"
        file = _write_yaml(tmp_path, data)
        with pytest.raises(PersonaLoadError, match="age"):
            load_persona(file)

    def test_raises_when_age_is_zero(self, tmp_path: Path) -> None:
        """age 字段为 0 时应抛出 PersonaLoadError（必须是正整数）"""
        data = _minimal_valid_yaml()
        data["age"] = 0
        file = _write_yaml(tmp_path, data)
        with pytest.raises(PersonaLoadError, match="age"):
            load_persona(file)

    def test_raises_when_age_is_negative(self, tmp_path: Path) -> None:
        """age 字段为负数时应抛出 PersonaLoadError"""
        data = _minimal_valid_yaml()
        data["age"] = -1
        file = _write_yaml(tmp_path, data)
        with pytest.raises(PersonaLoadError, match="age"):
            load_persona(file)

    def test_raises_when_string_field_is_empty(self, tmp_path: Path) -> None:
        """字符串字段为空字符串时应抛出 PersonaLoadError"""
        data = _minimal_valid_yaml()
        data["name"] = ""
        file = _write_yaml(tmp_path, data)
        with pytest.raises(PersonaLoadError, match="name"):
            load_persona(file)

    def test_raises_when_string_field_is_whitespace_only(self, tmp_path: Path) -> None:
        """字符串字段仅含空白时应抛出 PersonaLoadError"""
        data = _minimal_valid_yaml()
        data["tone"] = "   "
        file = _write_yaml(tmp_path, data)
        with pytest.raises(PersonaLoadError, match="tone"):
            load_persona(file)

    def test_raises_when_string_field_is_non_string(self, tmp_path: Path) -> None:
        """字符串字段为非字符串类型时应抛出 PersonaLoadError"""
        data = _minimal_valid_yaml()
        data["name"] = 12345
        file = _write_yaml(tmp_path, data)
        with pytest.raises(PersonaLoadError, match="name"):
            load_persona(file)


# ─────────────────────────────────────────────────────────────
# load_default_persona
# ─────────────────────────────────────────────────────────────

class TestLoadDefaultPersona:
    def test_returns_shen_zhiwei_persona(self) -> None:
        """load_default_persona 应返回沈知微人格"""
        persona = load_default_persona()
        assert isinstance(persona, PersonaProfile)
        assert persona.name == "沈知微"

    def test_raises_when_default_file_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """默认人格文件不存在时应抛出 PersonaLoadError"""
        import src.persona.registry as registry_module

        # 临时替换默认人格文件路径为不存在的路径
        monkeypatch.setattr(registry_module, "_DEFAULT_PERSONA_FILE", tmp_path / "nonexistent.yaml")
        with pytest.raises(PersonaLoadError):
            load_default_persona()


# ─────────────────────────────────────────────────────────────
# list_available_personas
# ─────────────────────────────────────────────────────────────

class TestListAvailablePersonas:
    def test_returns_yaml_filenames_in_default_dir(self) -> None:
        """默认 personas 目录应包含 shen_zhiwei.yaml 和 study_buddy.yaml"""
        names = list_available_personas()
        assert "shen_zhiwei.yaml" in names
        assert "study_buddy.yaml" in names

    def test_results_are_sorted_alphabetically(self) -> None:
        """返回列表应按字母顺序排序"""
        names = list_available_personas()
        assert names == sorted(names)

    def test_returns_only_yaml_files(self, tmp_path: Path) -> None:
        """只应返回 .yaml 和 .yml 扩展名的文件"""
        (tmp_path / "persona_a.yaml").write_text("a: 1", encoding="utf-8")
        (tmp_path / "persona_b.yml").write_text("b: 2", encoding="utf-8")
        (tmp_path / "README.md").write_text("# docs", encoding="utf-8")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / "script.py").write_text("pass", encoding="utf-8")

        names = list_available_personas(tmp_path)
        assert set(names) == {"persona_a.yaml", "persona_b.yml"}

    def test_returns_empty_list_for_empty_directory(self, tmp_path: Path) -> None:
        """空目录应返回空列表"""
        result = list_available_personas(tmp_path)
        assert result == []

    def test_returns_empty_list_for_nonexistent_directory(self, tmp_path: Path) -> None:
        """不存在的目录应返回空列表（而不是抛出异常）"""
        result = list_available_personas(tmp_path / "ghost_dir")
        assert result == []

    def test_returns_empty_list_when_path_is_file(self, tmp_path: Path) -> None:
        """指定路径是文件而非目录时应返回空列表"""
        file = tmp_path / "a_file.yaml"
        file.write_text("x: 1", encoding="utf-8")
        result = list_available_personas(file)
        assert result == []

    def test_accepts_str_and_path_types(self, tmp_path: Path) -> None:
        """personas_dir 参数应同时接受 str 和 Path"""
        (tmp_path / "x.yaml").write_text("x: 1", encoding="utf-8")
        assert list_available_personas(str(tmp_path)) == list_available_personas(tmp_path)

    def test_custom_dir_returns_correct_files(self, tmp_path: Path) -> None:
        """自定义目录应只返回该目录下的 YAML 文件，不受默认目录影响"""
        (tmp_path / "custom_persona.yaml").write_text("x: 1", encoding="utf-8")
        names = list_available_personas(tmp_path)
        assert names == ["custom_persona.yaml"]


# ─────────────────────────────────────────────────────────────
# 环境变量 PERSONA_FILE 覆盖集成测试
# ─────────────────────────────────────────────────────────────

class TestPersonaFileEnvVar:
    """
    测试 PERSONA_FILE 环境变量覆盖逻辑。
    这里直接测试 registry 模块的行为，
    而不依赖启动完整的 main.py 运行时。
    """

    def test_load_persona_from_env_var_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """PERSONA_FILE 指向有效文件时，应正确加载对应人格"""
        data = _minimal_valid_yaml()
        data["name"] = "环境变量人格"
        file = _write_yaml(tmp_path, data, "env_persona.yaml")

        monkeypatch.setenv("PERSONA_FILE", str(file))
        persona_path = os.environ.get("PERSONA_FILE", "")
        assert persona_path == str(file)

        # 直接调用 load_persona 模拟 main.py 读取 PERSONA_FILE 的行为
        persona = load_persona(persona_path)
        assert persona.name == "环境变量人格"

    def test_load_persona_env_var_invalid_path_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """PERSONA_FILE 指向不存在文件时，load_persona 应抛出 PersonaLoadError"""
        monkeypatch.setenv("PERSONA_FILE", str(tmp_path / "missing.yaml"))
        with pytest.raises(PersonaLoadError):
            load_persona(os.environ["PERSONA_FILE"])

    def test_without_env_var_load_default_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未设置 PERSONA_FILE 时，load_default_persona 应正常返回沈知微人格"""
        monkeypatch.delenv("PERSONA_FILE", raising=False)
        persona = load_default_persona()
        assert persona.name == "沈知微"

    def test_env_var_overrides_default_persona(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """PERSONA_FILE 设置后加载的人格名应与默认人格不同"""
        data = _minimal_valid_yaml()
        data["name"] = "覆盖人格"
        file = _write_yaml(tmp_path, data)

        monkeypatch.setenv("PERSONA_FILE", str(file))
        persona_file = os.environ.get("PERSONA_FILE", "").strip()
        loaded_persona = load_persona(persona_file) if persona_file else load_default_persona()

        assert loaded_persona.name == "覆盖人格"
        assert loaded_persona.name != SHEN_ZHIWEI_PROFILE.name

    def test_fallback_when_env_var_points_to_bad_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        模拟 main.py 中的回退逻辑：
        PERSONA_FILE 加载失败时，应回退到 Python 内联定义
        """
        monkeypatch.setenv("PERSONA_FILE", str(tmp_path / "nonexistent.yaml"))
        persona_file = os.environ.get("PERSONA_FILE", "").strip()

        # 模拟 main.py 的 try/except 回退逻辑
        try:
            active_persona = load_persona(persona_file)
        except PersonaLoadError:
            active_persona = SHEN_ZHIWEI_PROFILE

        assert active_persona is SHEN_ZHIWEI_PROFILE


# ─────────────────────────────────────────────────────────────
# PersonaLoadError 异常类型测试
# ─────────────────────────────────────────────────────────────

class TestPersonaLoadError:
    def test_is_exception_subclass(self) -> None:
        """PersonaLoadError 应是 Exception 的子类"""
        assert issubclass(PersonaLoadError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        """PersonaLoadError 应能正常被 raise 和 catch"""
        with pytest.raises(PersonaLoadError, match="测试错误消息"):
            raise PersonaLoadError("测试错误消息")

    def test_message_is_preserved(self) -> None:
        """错误消息应原样保留"""
        msg = "字段 'name' 缺失"
        err = PersonaLoadError(msg)
        assert str(err) == msg
