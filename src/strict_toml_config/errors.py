"""异常类型。"""

from __future__ import annotations


class ConfigError(ValueError):
    """配置读不了、或读到的值不合法。

    继承 :class:`ValueError` 有两个理由：

    - 调用方在只想「读不到就退出」时不用 import 这个库的类型，
      ``except ValueError`` 照样接得住
    - 但想专门接配置错误时又有得抓，不必和别的 ``ValueError`` 混在一起

    所有错误信息都带**文件名与点分键路径**（``app.toml: [review] max_cost 应为数值，实为 str``）——
    配置错误的排查成本全在「是哪个文件的哪个键」上，只说「类型不对」等于没说。
    """


def _where(path: str) -> str:
    """把点分键路径渲染成报错用的前缀。

    Args:
        path: 点分键路径；根层为空串

    Returns:
        ``"[review] "`` 形式；根层返回空串
    """
    return f"[{path}] " if path else ""
