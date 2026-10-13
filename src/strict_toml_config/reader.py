"""严格读取：**读的那一刻**就拦下配错的键。

三件事都在这里做，缺一件「配错看得见」就不成立：

1. **未知键**（拼错的、过期的、外来的）
2. **类型不符**（``max_lines = "500"`` —— tomllib 照收不误）
3. **取值越界**（有范围的整数、有枚举的字符串）

为什么必须在这里拦：``tomllib`` 只保证「是合法 TOML」，不保证「是我们的配置」。
字符串 ``"500"`` 会一路混到用它的地方才炸，那时离原因已经很远；而一个拼错的键
会被**静默忽略**，读到的永远是默认值 —— 那是最难发现的一类。

## 进一层先查未知键，再读值

顺序不能反。把 ``reserve_tokens`` 写成 ``reserve_token`` 时：

- 先读值 → 报「缺少 reserve_tokens」—— **指向错误方向**（键没少，是多了个拼错的）
- 先查未知键 → 报「存在未知配置项：reserve_token」—— 一眼看出是拼写问题
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from strict_toml_config.errors import ConfigError, _where
from strict_toml_config.schema import Schema


class Reader:
    """一层 toml 表，带严格校验的取值方法。

    不要直接构造 —— 从 :func:`load` 拿根层，再用 :meth:`section` 往下走。
    """

    def __init__(self, data: Mapping[str, Any], path: str, source: Path, schema: Schema) -> None:
        """初始化并校验键名。

        Args:
            data: 本层的原始字典
            path: 点分键路径，用于报错。根层为空串，往下是 ``tools.file_read`` 这种
            source: 配置文件路径，用于报错
            schema: 配置骨架

        Raises:
            ConfigError: 存在未知键
        """
        self._data = data
        self._path = path
        self._source = source
        self._schema = schema

        unknown = sorted(set(data) - schema.expected_keys(path))
        if unknown:
            raise ConfigError(f"{source.name}: {_where(path)}存在未知配置项：{', '.join(unknown)}")

    # ------------------------------------------------------------------ 内部

    def _fail(self, message: str) -> ConfigError:
        """构造带文件名与键路径的错误。

        Args:
            message: 错误描述

        Returns:
            填充好上下文的 ConfigError
        """
        return ConfigError(f"{self._source.name}: {_where(self._path)}{message}")

    def _raw(self, key: str) -> Any:
        """取出某个键的原始值。

        未知键在 ``__init__`` 就挡掉了，所以走到这里还缺，只可能是键被删了。

        Args:
            key: 键名

        Returns:
            原始值

        Raises:
            ConfigError: 该键缺失
        """
        if key not in self._data:
            raise self._fail(f"缺少配置项 {key}")
        return self._data[key]

    # ------------------------------------------------------------ 标量取值

    def text(self, key: str) -> str:
        """读一个字符串。

        Args:
            key: 键名

        Returns:
            字符串值

        Raises:
            ConfigError: 缺失或类型不符
        """
        value = self._raw(key)
        if not isinstance(value, str):
            raise self._fail(f"{key} 应为字符串，实为 {type(value).__name__}")
        return value

    def count(self, key: str) -> int:
        """读一个整数。

        **``true`` 要单独挡掉** —— 它 ``isinstance(True, int)`` 为真，不挡的话
        ``max_lines = true`` 会静默变成 1。

        Args:
            key: 键名

        Returns:
            整数值

        Raises:
            ConfigError: 缺失或类型不符
        """
        value = self._raw(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise self._fail(f"{key} 应为整数，实为 {type(value).__name__}")
        return value

    def number(self, key: str) -> float:
        """读一个数（整数或小数都收，统一成 ``float``）。

        预算与价格这类值天然是小数（2.0 元、0.5 元/百万）。**同样不接 ``bool``** ——
        理由与 :meth:`count` 一样。

        Args:
            key: 键名

        Returns:
            浮点值

        Raises:
            ConfigError: 缺失或类型不符
        """
        value = self._raw(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise self._fail(f"{key} 应为数值，实为 {type(value).__name__}")
        return float(value)

    # ------------------------------------------------------------ 受限取值

    def bounded_count(self, key: str, *, low: int, high: int) -> int:
        """读一个有取值范围的整数。

        **越界直接报错，不夹到边界。** 夹一下看起来更「友好」，但那正是最难查的
        那类错：用户写了 16、跑出来的是 8，而两者都不报错。范围本身是契约
        （``run(config.py)`` 里写了为什么是这个区间），不该被静默改写。

        Args:
            key: 键名
            low: 允许的最小值（含）
            high: 允许的最大值（含）

        Returns:
            整数值

        Raises:
            ConfigError: 缺失、类型不符或越界
        """
        value = self.count(key)
        if not low <= value <= high:
            raise self._fail(f"{key} 必须在 {low}..{high} 之间，实为 {value}")
        return value

    def choice(self, key: str, *, allowed: tuple[str, ...] | frozenset[str]) -> str:
        """读一个取值受限的字符串。

        与 :meth:`bounded_count` 同一条判据：不在允许集合里就地报错，不回落、
        不降级。这类值配错的后果同样是**静默的** —— 上游很可能不认识这个取值，
        于是安静地按默认行为跑，而「跑的是哪个档」可能直接决定花多少钱。

        Args:
            key: 键名
            allowed: 允许的取值。**用元组可以控制报错信息里的展示顺序**

        Returns:
            字符串值

        Raises:
            ConfigError: 缺失、类型不符或不在允许集合内
        """
        value = self.text(key)
        if value not in allowed:
            listed = "/".join(allowed) if isinstance(allowed, tuple) else "/".join(sorted(allowed))
            raise self._fail(f"{key} 必须是 {listed} 之一，实为 {value!r}")
        return value

    def numbers(self, key: str) -> tuple[int, ...]:
        """读一个整数数组。

        Args:
            key: 键名

        Returns:
            整数元组

        Raises:
            ConfigError: 缺失或元素类型不符
        """
        value = self._raw(key)
        if not isinstance(value, list) or not all(
            isinstance(item, int) and not isinstance(item, bool) for item in value
        ):
            raise self._fail(f"{key} 应为整数数组")
        return tuple(value)

    # -------------------------------------------------------------- 往下走

    def section(self, key: str) -> Reader:
        """进入下一层表。

        新一层的键名会**在建出来的那一刻**校验，所以进入一个拼错的段名不会
        悄悄拿到一个空段。

        Args:
            key: 子段名

        Returns:
            子层的 Reader

        Raises:
            ConfigError: 缺失或不是表
        """
        value = self._raw(key)
        if not isinstance(value, dict):
            raise self._fail(f"{key} 应为配置段")
        return Reader(value, f"{self._path}.{key}".lstrip("."), self._source, self._schema)


def load(path: Path, schema: Schema) -> Reader:
    """读一个 toml 文件，返回根层的 :class:`Reader`。

    **只做读取与校验，不认识任何具体的配置项** —— 每段该读哪些键、组装成什么
    类型，由调用方用返回的 Reader 自己写。这样库不用知道你的配置长什么样。

    **键名是整棵树一次验完的**（见 :func:`_walk`），不是走到哪验到哪 ——
    否则一个拼错的键会一直安静，直到有人碰巧读了它所在的那个段。

    值（类型、范围）仍然由调用方在读的时候验：库不知道你打算用哪个取值方法。

    Args:
        path: 配置文件路径
        schema: 配置骨架

    Returns:
        根层 Reader

    Raises:
        ConfigError: 文件读不了、不是合法 TOML、或**任意一层**存在未知键；
            文件不存在（``FileNotFoundError``）与权限问题（``PermissionError``）
            原样抛出 —— 那是环境问题，不是配置写错
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path.name}: 不是 UTF-8 编码的文本文件") from exc

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path.name}: 不是合法的 TOML —— {exc}") from exc

    root = Reader(data, "", path, schema)
    _walk(data, "", path, schema)
    return root


def _walk(data: Mapping[str, Any], path: str, source: Path, schema: Schema) -> None:
    """把文件里**存在的**每一个已声明段都构造一遍。

    构造即校验 —— :class:`Reader.__init__` 会查这一层的未知键。不做这一步的话，
    子段的键要等调用方走到 ``section()`` 才验，那「读的那一刻就报出来」就打了折扣：
    一个拼错的键会一直安安静静，直到有人碰巧读了它所在的那个段。

    **只往下走已声明的段**：未声明的段在父层就已经被当成未知键报掉了，这里
    再往下走只会撞上「骨架里没有这个段」的 ``KeyError`` —— 那是编程错误，
    不是用户配置的问题。

    Args:
        data: 本层的原始字典
        path: 本层的点分键路径；根层为空串
        source: 配置文件路径
        schema: 配置骨架
    """
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        child = f"{path}.{key}".lstrip(".")
        if child not in schema.sections and child not in schema.containers:
            continue
        Reader(value, child, source, schema)
        _walk(value, child, source, schema)
