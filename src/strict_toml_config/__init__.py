"""严格 TOML 配置读取：配错了在读的那一刻就报出来。

    >>> from strict_toml_config import Reader, Schema, load
    >>> schema = Schema(sections={"server": (Server, frozenset())})
    >>> root = load(Path("app.toml"), schema)
    >>> server = root.section("server")
    >>> Server(host=server.text("host"), port=server.bounded_count("port", low=1, high=65535))

拦三类错，都在读的那一刻、都带文件名与键路径：

- **未知键** —— 拼错的、过期的会被静默忽略，读到的永远是默认值
- **类型不符** —— ``tomllib`` 只保证「是合法 TOML」，``max_lines = "500"`` 照收
- **取值越界** —— 有范围的整数与有枚举的字符串，越界就报，不夹到边界
"""

from strict_toml_config.errors import ConfigError
from strict_toml_config.reader import Reader, load
from strict_toml_config.schema import Schema, schema_of

__all__ = [
    "ConfigError",
    "Reader",
    "Schema",
    "load",
    "schema_of",
]
