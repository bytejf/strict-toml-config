# strict-toml-config

[![CI](https://github.com/bytejf/strict-toml-config/actions/workflows/ci.yml/badge.svg)](https://github.com/bytejf/strict-toml-config/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)
[![Zero deps](https://img.shields.io/badge/dependencies-0-brightgreen?style=flat-square)](pyproject.toml)

**配错了，在读的那一刻就报出来** —— 并且告诉你**是哪个文件的哪个键**。

```python
from strict_toml_config import ConfigError, Schema, load


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    token: str = ""  # 从环境变量读，不出现在 toml 里


SCHEMA = Schema(sections={"server": (ServerConfig, frozenset({"token"}))})


def load_config(path: Path) -> ServerConfig:
    server = load(path, SCHEMA).section("server")
    return ServerConfig(
        host=server.text("host"),
        port=server.bounded_count("port", low=1, high=65535),
    )
```

```
app.toml: [server] port 必须在 1..65535 之间，实为 70000
app.toml: [server] 存在未知配置项：hosst
app.toml: [server] workers 应为整数，实为 bool
```

---

## 为什么

`tomllib` 只保证「这是一份**合法 TOML**」，不保证「这是**我们的配置**」。
中间那段路有三类错，全都会**静默**发生：

| 你写的 | 标准库的行为 | 后果 |
|---|---|---|
| 把 `max_lines` 拼成 `max_line` | 完全不报错 | 那个键被忽略，读到的是默认值 —— **你以为改了，其实没改** |
| `max_lines = "500"` | 照收（TOML 里字符串合法） | 一路混到用它的地方才炸，那时离原因已经很远 |
| `concurrency = 16`（上限 8） | 照收 | 要么在后面某处崩，要么更糟 —— 被夹成 8 而没人告诉你 |

第三类还有个变体：库「贴心地」把越界值**夹到边界**。那比报错更糟 ——
用户写了 16、跑出来的是 8，**两者都不报错**。

`strict-toml-config` 的选择是：**在这三类错面前，宁可吵，不可猜**。

## 安装

```bash
pip install strict-toml-config
```

零依赖，只用标准库。Python 3.11+（`tomllib` 是 3.11 才进的）。

## 用法

### 1. 声明骨架

骨架只描述**形状**：哪些段可以出现、每段允许哪些键。

```python
from dataclasses import dataclass
from strict_toml_config import Schema, schema_of


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    workers: int


@dataclass(frozen=True)
class RetryConfig:
    times: int
    backoff: float


# 所有字段都该出现在 toml 里 —— 用这个简写
SCHEMA = schema_of(
    {"server": ServerConfig, "server.retry": RetryConfig},
    containers={"logging": {"file", "console"}},
)
```

**期望的键是从数据类的字段推出来的，不用另写一份键名清单。** 写第二份清单
意味着加了字段容易忘了同步 —— 而漏掉的后果同样是「那个键被静默忽略」。

只有两类要显式声明：

- **排除字段** —— 「故意不从 toml 读」的那些。密钥从环境变量来、窗口由模型决定、
  常量不做成旋钮，都属于这一类：

  ```python
  SCHEMA = Schema(sections={"server": (ServerConfig, frozenset({"token"}))})
  ```

- **容器段** —— 只当容器用的段，它的键必须是子段名：

  ```python
  Schema(sections={...}, containers={"logging": frozenset({"file", "console"})})
  ```

### 2. 读

```python
from pathlib import Path
from strict_toml_config import load

root = load(Path("app.toml"), SCHEMA)
server = root.section("server")
```

`load` 只做「解析 + 校验键名」，**不认识任何具体的配置项** —— 每段读哪些键、
组装成什么类型，由你写。这样库不需要知道你的配置长什么样。

### 3. 取值方法

| 方法 | 读什么 | 配错时 |
|---|---|---|
| `text(key)` | 字符串 | 类型不符报错 |
| `count(key)` | 整数 | 类型不符报错（**`true` 不算整数**） |
| `number(key)` | 数值（整数或小数，统一成 `float`） | 类型不符报错（**`true` 也不算**） |
| `numbers(key)` | 整数数组 | 元素类型不符报错 |
| `bounded_count(key, low=, high=)` | 有范围的整数 | **越界报错，不夹到边界** |
| `choice(key, allowed=)` | 取值受限的字符串 | 不在集合里报错 |
| `section(key)` | 下一层表 | 缺失 / 不是表报错 |

`choice` 传**元组**时，元组的顺序就是报错信息里的展示顺序：

```python
effort = cfg.choice("reasoning_effort", allowed=("none", "low", "high", "max"))
```

### 错误信息

所有错误都带**文件名 + 点分键路径**：

```
app.toml: [server] port 应为整数，实为 str
app.toml: [server] 存在未知配置项：hosst
app.toml: [a.b] times 应为整数，实为 str
```

配置错误的排查成本全在「是哪个文件的哪个键」上，只说「类型不对」等于没说。

异常类型是 `ConfigError`，它**继承 `ValueError`**：

```python
from strict_toml_config import ConfigError

try:
    settings = load_config(path)
except ConfigError as exc:  # 想专门处理配置错误时
    ...
except ValueError:  # 只写这个也接得住
    ...
```

**文件不存在与权限问题原样抛出**（`FileNotFoundError` / `PermissionError`）——
那是环境问题，不是配置写错，包成 `ConfigError` 会让人分不清该改哪边。

## 设计要点

**1. 进一层先查未知键，再读值。** 顺序不能反。

把 `retry_times` 写成 `retry_time` 时：

- 先读值 → 报「缺少 retry_times」——**指向错误方向**（键没少，是多了个拼错的）
- 先查未知键 → 报「存在未知配置项：retry_time」—— 一眼看出是拼写问题

**2. 期望的键只有一份来源。** 从数据类的字段推出来。骨架是读取与校验**共用**
的那份定义，所以它自己不可能偏 —— 偏了立刻报未知键。

**3. 越界不夹到边界。** 夹一下看起来更「友好」，但那正是最难查的那类错。
范围本身是契约（代码里写了为什么是这个区间），不该被静默改写。

**4. `bool` 要单独挡掉。** `isinstance(True, int)` 为真 —— 不挡的话
`workers = true` 会静默变成 1。

**5. 骨架与代码对不上时报 `KeyError`，不报 `ConfigError`。**
问一个没声明的段是**编程错误**，不是用户配置的问题。报成配置错误会把人
往配置文件上带。

## 边界

- **不校验跨字段的约束。** 「A 必须小于 B」「这三个键要么都给要么都不给」这类
  得在读完之后自己写 —— 库只做**单键**的类型与取值校验。
- **不做默认值填充。** 缺键就是缺键，报出来。想给默认值就在数据类里写
  `field(default=...)`，别让库猜。
- **不读环境变量、不认识文件布局。** 它只读你给的那个路径。
- **不做热重载 / 监听。** 自己决定什么时候重新 `load`。

## 开发

```bash
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
```

## License

[MIT](LICENSE)
