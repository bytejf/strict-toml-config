"""读取与校验的单元测试。

守的是**「配错了看得见」**这件事本身：未知键、类型不符、取值越界，三类都要
在读的那一刻炸，且错误信息要能指出是哪个文件的哪个键。

**注意 `load()` 与取值方法的分工**：`load()` 校验键名（未知键、非法 TOML），
取值方法校验**值**（类型、范围）。所以验值的用例必须真的去读那个键 —— 这正是
真实调用方要做的事，`load_server` 就是照着那个形状写的。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from strict_toml_config import ConfigError, Reader, Schema, load, schema_of


@dataclass(frozen=True)
class ServerConfig:
    """测试用：一个普通段。"""

    host: str
    port: int
    workers: int
    ratio: float
    levels: list[int]
    token: str = ""


@dataclass(frozen=True)
class RetryConfig:
    """测试用：嵌套段。"""

    times: int
    backoff: float


BASE = """\
[server]
host = "127.0.0.1"
port = 8080
workers = 4
ratio = 0.75
levels = [1, 2]
token = "secret"

[retry]
times = 3
backoff = 0.5
"""

SCHEMA = Schema(
    sections={"server": (ServerConfig, frozenset()), "retry": (RetryConfig, frozenset())}
)


def write(tmp_path: Path, text: str, name: str = "app.toml") -> Path:
    """把配置文本落到临时文件。

    Args:
        tmp_path: 临时目录
        text: 配置文本
        name: 文件名

    Returns:
        文件路径
    """
    target = tmp_path / name
    target.write_text(text, encoding="utf-8")
    return target


def read(tmp_path: Path, text: str = BASE) -> Reader:
    """读一段配置文本，返回根层 Reader（**只校验键名，不读值**）。

    Args:
        tmp_path: 临时目录
        text: 配置文本

    Returns:
        根层 Reader
    """
    return load(write(tmp_path, text), SCHEMA)


def load_server(tmp_path: Path, text: str = BASE) -> ServerConfig:
    """照着真实调用方的形状把 ``[server]`` 段读成一个对象。

    取值错误只会在这一步炸 —— `load()` 不认识任何具体的键。

    Args:
        tmp_path: 临时目录
        text: 配置文本

    Returns:
        ServerConfig
    """
    server = read(tmp_path, text).section("server")
    return ServerConfig(
        host=server.text("host"),
        port=server.count("port"),
        workers=server.count("workers"),
        ratio=server.number("ratio"),
        levels=list(server.numbers("levels")),
        token=server.text("token"),
    )


# ---------------------------------------------------------------- 正常路径


def test_reads_every_scalar_type(tmp_path: Path) -> None:
    """字符串 / 整数 / 小数 / 整数数组都能读出来。"""
    server = read(tmp_path).section("server")

    assert server.text("host") == "127.0.0.1"
    assert server.count("port") == 8080
    assert server.number("ratio") == 0.75
    assert server.numbers("levels") == (1, 2)


def test_number_accepts_an_integer_too(tmp_path: Path) -> None:
    """``number`` 收整数也收小数，统一成 float。

    预算从 ``2`` 改成 ``2.5`` 时不该要求写者也改写法。
    """
    retry = read(tmp_path).section("retry")

    assert retry.number("times") == 3.0
    assert isinstance(retry.number("times"), float)


def test_a_whole_section_reads_into_its_model(tmp_path: Path) -> None:
    """一整段能读成对象 —— 真实调用方的形状。"""
    config = load_server(tmp_path)

    assert config == ServerConfig("127.0.0.1", 8080, 4, 0.75, [1, 2], "secret")


# ------------------------------------------------------------------ 未知键


def test_unknown_key_in_section_is_rejected(tmp_path: Path) -> None:
    """段里多出一个没人认识的键 → 报错。

    这条比类型错更重要：拼错的键会被**静默忽略**，读到的永远是默认值。
    """
    text = BASE.replace('host = "127.0.0.1"', 'hosst = "127.0.0.1"\nhost = "127.0.0.1"')

    with pytest.raises(ConfigError, match=r"\[server\] 存在未知配置项：hosst"):
        read(tmp_path, text)


def test_unknown_section_is_rejected(tmp_path: Path) -> None:
    """顶层多出一个段 → 报错。"""
    with pytest.raises(ConfigError, match=r"存在未知配置项：extra"):
        read(tmp_path, BASE + "\n[extra]\nx = 1\n")


def test_unknown_keys_are_checked_before_values(tmp_path: Path) -> None:
    """**先查未知键、再读值** —— 顺序反了会给出指向错误方向的提示。

    把 ``host`` 写成 ``hoost`` 时，先读值会报「缺少 host」；而键并没有少，
    是多了一个拼错的。先查未知键，报出来的就是 ``hoost`` 本身。
    """
    text = BASE.replace('host = "127.0.0.1"', 'hoost = "127.0.0.1"')

    with pytest.raises(ConfigError) as excinfo:
        read(tmp_path, text)

    assert "hoost" in str(excinfo.value)
    assert "缺少" not in str(excinfo.value)


# -------------------------------------------------------------------- 类型


def test_wrong_type_is_rejected(tmp_path: Path) -> None:
    """``max_lines = "500"`` 这种写法 tomllib 照收，我们照拒。"""
    with pytest.raises(ConfigError, match=r"port 应为整数，实为 str"):
        load_server(tmp_path, BASE.replace("port = 8080", 'port = "8080"'))


def test_wrong_string_type_is_rejected(tmp_path: Path) -> None:
    """字符串位置给了数字。"""
    with pytest.raises(ConfigError, match=r"host 应为字符串，实为 int"):
        load_server(tmp_path, BASE.replace('host = "127.0.0.1"', "host = 1"))


def test_bool_is_not_an_int(tmp_path: Path) -> None:
    """``true`` 不算整数。

    ``isinstance(True, int)`` 为真，不挡的话 ``workers = true`` 会静默变成 1。
    """
    with pytest.raises(ConfigError, match=r"workers 应为整数，实为 bool"):
        load_server(tmp_path, BASE.replace("workers = 4", "workers = true"))


def test_bool_is_not_a_number(tmp_path: Path) -> None:
    """``true`` 也不算数值 —— 与 ``count`` 同一个坑。"""
    with pytest.raises(ConfigError, match=r"ratio 应为数值，实为 bool"):
        load_server(tmp_path, BASE.replace("ratio = 0.75", "ratio = true"))


def test_wrong_element_type_in_array_is_rejected(tmp_path: Path) -> None:
    """整数数组里混进字符串。"""
    with pytest.raises(ConfigError, match=r"levels 应为整数数组"):
        load_server(tmp_path, BASE.replace("levels = [1, 2]", 'levels = [1, "b"]'))


def test_missing_key_names_the_key(tmp_path: Path) -> None:
    """缺键报出的是键名。"""
    text = "\n".join(line for line in BASE.splitlines() if not line.startswith("port"))

    with pytest.raises(ConfigError, match=r"缺少配置项 port"):
        load_server(tmp_path, text)


# ---------------------------------------------------------------- 取值受限


def test_bounded_count_out_of_range_is_a_hard_error(tmp_path: Path) -> None:
    """越界**硬报错**，不静默夹到边界。

    夹一下看起来更「友好」，但用户写了 16、跑出来的是 8，两者都不报错。
    """
    server = read(tmp_path).section("server")

    assert server.bounded_count("port", low=1, high=65535) == 8080
    with pytest.raises(ConfigError, match=r"port 必须在 10000\.\.20000 之间，实为 8080"):
        server.bounded_count("port", low=10000, high=20000)


def test_bounded_count_accepts_the_boundaries(tmp_path: Path) -> None:
    """边界值本身合法。"""
    server = read(tmp_path).section("server")

    assert server.bounded_count("port", low=8080, high=8080) == 8080


def test_choice_accepts_a_listed_value(tmp_path: Path) -> None:
    """在集合里就收。"""
    server = read(tmp_path).section("server")

    assert server.choice("host", allowed=("127.0.0.1", "0.0.0.0")) == "127.0.0.1"


def test_choice_rejects_a_value_outside_the_set(tmp_path: Path) -> None:
    """不在集合里就报错，并列出允许的取值。"""
    server = read(tmp_path).section("server")

    with pytest.raises(ConfigError, match=r"host 必须是 z/a/m 之一，实为 '127\.0\.0\.1'"):
        server.choice("host", allowed=("z", "a", "m"))


def test_choice_shows_the_tuple_order_in_the_message(tmp_path: Path) -> None:
    """元组的顺序就是报错信息里的展示顺序 —— 想让它跟业务优先级走时用元组。"""
    server = read(tmp_path).section("server")

    with pytest.raises(ConfigError) as excinfo:
        server.choice("host", allowed=("none", "low", "high", "max"))

    assert "none/low/high/max" in str(excinfo.value)


def test_choice_accepts_a_frozenset_too(tmp_path: Path) -> None:
    """集合也能传；展示顺序按字母排（集合本来就没有顺序）。"""
    server = read(tmp_path).section("server")

    with pytest.raises(ConfigError) as excinfo:
        server.choice("host", allowed=frozenset({"b", "a"}))

    assert "a/b" in str(excinfo.value)


# -------------------------------------------------------------------- 段


def test_section_missing_is_rejected(tmp_path: Path) -> None:
    """要一个不存在的段。"""
    with pytest.raises(ConfigError, match=r"缺少配置项 nope"):
        read(tmp_path).section("nope")


def test_section_that_is_not_a_table_is_rejected(tmp_path: Path) -> None:
    """段位置给了一个标量。

    （``retry = 1`` 必须写在 ``[server]`` **之前** —— toml 里段头之后的所有
    键值对都属于那个段。）
    """
    text = (
        "retry = 1\n\n"
        '[server]\nhost = "h"\nport = 1\nworkers = 1\nratio = 1.0\nlevels = []\ntoken = ""\n'
    )

    with pytest.raises(ConfigError, match=r"retry 应为配置段"):
        read(tmp_path, text).section("retry")


def test_nested_section_reports_a_dotted_key_path(tmp_path: Path) -> None:
    """嵌套段的报错带点分路径，与 toml 的段名写法一致。"""
    schema = Schema(
        sections={
            "a": (ServerConfig, frozenset()),
            "a.b": (RetryConfig, frozenset()),
        }
    )
    text = (
        '[a]\nhost = "h"\nport = 1\nworkers = 1\nratio = 1.0\nlevels = []\ntoken = ""\n\n'
        '[a.b]\ntimes = "x"\nbackoff = 1.0\n'
    )

    with pytest.raises(ConfigError, match=r"app\.toml: \[a\.b\] times 应为整数"):
        load(write(tmp_path, text), schema).section("a").section("b").count("times")


def test_container_section_lists_sub_sections(tmp_path: Path) -> None:
    """容器段的键必须是声明的子段名。"""
    schema = Schema(
        sections={"tools.file": (RetryConfig, frozenset())},
        containers={"tools": frozenset({"file"})},
    )
    text = "[tools.file]\ntimes = 1\nbackoff = 0.5\n"

    assert load(write(tmp_path, text), schema).section("tools").section("file").count("times") == 1


def test_container_section_rejects_a_key_that_is_not_a_sub_section(tmp_path: Path) -> None:
    """容器段里出现一个不是子段的键。"""
    schema = Schema(
        sections={"tools.file": (RetryConfig, frozenset())},
        containers={"tools": frozenset({"file"})},
    )
    text = "[tools.file]\ntimes = 1\nbackoff = 0.5\n\n[tools.other]\nx = 1\n"

    with pytest.raises(ConfigError, match=r"\[tools\] 存在未知配置项：other"):
        load(write(tmp_path, text), schema)


# ------------------------------------------------------------ 错误信息


def test_error_names_the_file(tmp_path: Path) -> None:
    """报错必须带文件名 —— 一台机器上可能有好几份配置。

    用**未知键**来验：它发生在 ``load()`` 里；验值的错要读到那个键才炸。
    """
    text = BASE.replace('host = "127.0.0.1"', 'hosst = "127.0.0.1"')

    with pytest.raises(ConfigError, match=r"^my\.toml: "):
        load(write(tmp_path, text, "my.toml"), SCHEMA)


def test_value_error_names_the_file_too(tmp_path: Path) -> None:
    """取值错也带文件名与键路径 —— 走的是同一条 ``_fail``。"""
    with pytest.raises(ConfigError, match=r"^app\.toml: \[server\] "):
        load_server(tmp_path, BASE.replace("port = 8080", 'port = "x"'))


def test_error_names_the_key_path(tmp_path: Path) -> None:
    """报错必须带键路径。"""
    with pytest.raises(ConfigError, match=r"\[server\] port 应为整数"):
        load_server(tmp_path, BASE.replace("port = 8080", 'port = "x"'))


def test_config_error_is_a_value_error(tmp_path: Path) -> None:
    """``ConfigError`` 继承 ``ValueError`` —— 只写 ``except ValueError`` 也接得住。"""
    assert issubclass(ConfigError, ValueError)

    with pytest.raises(ValueError):
        load_server(tmp_path, BASE.replace("port = 8080", 'port = "x"'))


# ---------------------------------------------------------------- load


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    """文件不存在**原样**抛 ``FileNotFoundError``。

    那是环境问题（路径写错、包装在别处），不是配置写错 —— 包成 ConfigError
    会让人分不清该去改配置还是改调用方。
    """
    with pytest.raises(FileNotFoundError):
        load(tmp_path / "nope.toml", SCHEMA)


def test_broken_toml_is_reported_as_config_error(tmp_path: Path) -> None:
    """语法错的 toml 变成 ConfigError，原异常挂在 ``__cause__`` 上。"""
    with pytest.raises(ConfigError, match=r"不是合法的 TOML") as excinfo:
        read(tmp_path, "this is not toml\n")

    assert excinfo.value.__cause__ is not None


def test_non_utf8_file_is_reported_as_config_error(tmp_path: Path) -> None:
    """非 UTF-8 文件给出能看懂的提示，而不是一串解码细节。"""
    target = tmp_path / "app.toml"
    target.write_bytes(b"\xff\xfe\x00\x00")

    with pytest.raises(ConfigError, match=r"不是 UTF-8"):
        load(target, SCHEMA)


def test_empty_file_still_has_a_root_reader(tmp_path: Path) -> None:
    """空文件里连段都没有 —— 要段的时候才报。"""
    with pytest.raises(ConfigError, match=r"缺少配置项 server"):
        read(tmp_path, "").section("server")


# ---------------------------------------------------------------- Schema


def test_schema_derives_expected_keys_from_dataclass_fields() -> None:
    """期望的键从**数据类的字段**推出来，不另写一份会漂移的清单。"""
    assert SCHEMA.expected_keys("server") == {
        "host",
        "port",
        "workers",
        "ratio",
        "levels",
        "token",
    }


def test_schema_excludes_the_declared_fields() -> None:
    """被排除的字段不出现在期望键里 —— 那是「故意不从 toml 读」的那些。"""
    schema = Schema(sections={"server": (ServerConfig, frozenset({"token"}))})

    assert "token" not in schema.expected_keys("server")
    assert "host" in schema.expected_keys("server")


def test_excluded_field_is_rejected_when_present_in_the_file(tmp_path: Path) -> None:
    """排除字段真的写进 toml 反而是未知键 —— 那份清单只有一处来源。"""
    schema = Schema(sections={"server": (ServerConfig, frozenset({"token"}))})
    text = '[server]\nhost = "h"\nport = 1\nworkers = 1\nratio = 1.0\nlevels = []\ntoken = "x"\n'

    with pytest.raises(ConfigError, match=r"存在未知配置项：token"):
        load(write(tmp_path, text), schema)


def test_schema_root_lists_top_level_sections_only() -> None:
    """根层的期望键是**段名**，不是配置项。"""
    assert SCHEMA.expected_keys("") == {"server", "retry"}


def test_schema_rejects_an_undeclared_section() -> None:
    """问一个没声明的段 → ``KeyError``。

    这是**编程错误**（骨架和代码对不上），不是用户配置的问题 —— 所以不能报成
    ConfigError，否则会把人往配置文件上带。
    """
    with pytest.raises(KeyError, match="骨架里没有段"):
        SCHEMA.expected_keys("nope")


def test_schema_is_frozen() -> None:
    """骨架建完之后不能再改。"""
    with pytest.raises(TypeError):
        SCHEMA.sections["new"] = (ServerConfig, frozenset())  # type: ignore[index]


def test_schema_of_fills_in_the_empty_exclusion() -> None:
    """``schema_of`` 省掉「所有字段都该出现」时的 ``(类, frozenset())`` 壳。"""
    schema = schema_of({"retry": RetryConfig}, containers={"tools": {"x"}})

    assert schema.expected_keys("retry") == {"times", "backoff"}
    assert schema.expected_keys("tools") == {"x"}


def test_expected_keys_of_an_empty_container() -> None:
    """容器段声明为空 → 那个段不该有任何键。"""
    schema = Schema(sections={"a": (RetryConfig, frozenset())}, containers={"empty": frozenset()})

    assert schema.expected_keys("empty") == frozenset()
