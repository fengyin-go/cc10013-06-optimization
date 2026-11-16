"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

import copy
from typing import Any

from app.seed import SEED_ROWS

# 从属数据集：跟随主模块一起存储，但不作为独立业务模块出现在运营概览里。
# 频率预算数据集（窗口占用记录）就是频率规则的下属数据。
AUXILIARY_MODULES = {"freq_window"}


class Store:
    def __init__(self) -> None:
        self._load()

    def _load(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: copy.deepcopy(rows) for name, rows in SEED_ROWS.items()
        }
        # 每个模块一条单调递增的占用版本；规则页、监控待处理清单都读这一份。
        self._versions: dict[str, int] = {}
        for name, rows in self._tables.items():
            self._versions[name] = max(
                (self._version_of(row) for row in rows),
                default=0,
            )

    @staticmethod
    def _version_of(row: dict[str, Any]) -> int:
        try:
            return int(row.get("占用版本", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def reset(self) -> None:
        """恢复到示例数据；测试与本地演示可以借它重复跑同一套取数口径。"""
        self._load()

    def module_names(self) -> list[str]:
        return sorted(name for name in self._tables if name not in AUXILIARY_MODULES)

    def version(self, module: str) -> int:
        """读取模块当前的占用版本；没有变更时返回初始版本。"""
        return self._versions.get(module, 0)

    def bump_version(self, module: str) -> int:
        """每次窗口结果落库后推进一次占用版本，页面据此判断是否读到同一份结果。"""
        self._versions[module] = self.version(module) + 1
        return self._versions[module]

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
