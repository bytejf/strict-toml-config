"""配置骨架：哪些段可以出现、每段允许哪些键。

**期望的键由数据类的字段推出来，不另写一份键名清单** —— 那会是第二份会漂移
的东西：加了字段忘了改清单，配置就永远读不到那个键，而且不报错。

只有两处要显式声明：

- `sections` 里每段的**排除字段** —— 那些「故意不出现在 toml 里」的字段
  （从环境变量读的密钥、被上游决定的值、不做成旋钮的常量）
- `containers` —— 只当容器的段，它的键是子段名而不是配置项
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class Schema:
    """配置骨架。

    Attributes:
        sections: 段路径 → ``(数据类, 故意不出现的字段名)``。段路径用点分写法，
            与 toml 的段名一致（``"tools.file_read"``）
        containers: 只当容器的段路径 → 该段允许出现的子段名。容器段自己不是配置项，
            它的键必须是子段

    Example:
        >>> Schema(
        ...     sections={"server": (Server, frozenset({"internal_token"}))},
        ...     containers={"logging": frozenset({"file", "console"})},
        ... )
    """

    sections: Mapping[str, tuple[type, frozenset[str]]]
    containers: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """冻结两份映射，避免建完之后被改。"""
        object.__setattr__(self, "sections", MappingProxyType(dict(self.sections)))
        object.__setattr__(self, "containers", MappingProxyType(dict(self.containers)))

    def expected_keys(self, path: str) -> frozenset[str]:
        """某一层允许出现哪些键。

        根层给出的是**子段名**，不是配置项 —— toml 的顶层只放段。

        一个段可以**同时**是配置项与容器，这正是 ``[server]`` + ``[server.tls]``
        的常见写法，所以三层都要算进来：

        - 声明为容器时，它允许的子段名
        - 声明为配置段时，它的数据类字段（减去排除字段）
        - **路径在它下面的**那些段的第一段名

        第三条让「容器段不必逐个列出子段」也能工作。

        Args:
            path: 点分键路径，根层为空串

        Returns:
            允许的键集合；该段本来就不该有键时为空集合
        """
        if not path:
            return frozenset(name.split(".")[0] for name in (*self.sections, *self.containers))
        if path not in self.sections and path not in self.containers:
            # 走到这里说明骨架与代码对不上（比如 section() 的路径写错了），
            # 不是用户配置的问题 —— 所以它是个编程错误，不是 ConfigError
            msg = f"骨架里没有段 {path!r}：请检查 Schema.sections / containers"
            raise KeyError(msg)

        keys = set(self.containers.get(path, ()))
        if path in self.sections:
            model, excluded = self.sections[path]
            keys |= {item.name for item in fields(model)} - excluded
        keys |= self._child_section_names(path)
        return frozenset(keys)

    def _child_section_names(self, path: str) -> set[str]:
        """路径在 ``path`` 下面的段，各自的第一段名。

        Args:
            path: 点分键路径

        Returns:
            子段名集合；没有子段时为空集合
        """
        prefix = f"{path}."
        return {
            name[len(prefix) :].split(".")[0]
            for name in (*self.sections, *self.containers)
            if name.startswith(prefix)
        }

    def known_section(self, path: str) -> bool:
        """这个路径是不是一个已声明的段。

        Args:
            path: 点分键路径

        Returns:
            已声明为配置段返回 True
        """
        return path in self.sections


def schema_of(sections: Mapping[str, Any], containers: Mapping[str, Any] | None = None) -> Schema:
    """把 ``{路径: 数据类}`` 写法的骨架补全成 :class:`Schema`。

    给「所有字段都该出现在 toml 里」这种常见情形省掉一层 ``(类, frozenset())``
    的壳。

    Args:
        sections: 段路径 → 数据类
        containers: 容器段路径 → 允许的子段名

    Returns:
        Schema
    """
    return Schema(
        sections={path: (model, frozenset()) for path, model in sections.items()},
        containers=dict(containers) if containers else {},
    )
