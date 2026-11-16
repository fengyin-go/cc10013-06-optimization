"""频率预算数据集的回归用例：重复启用、占用版本一致性与迟到更正冲突。

直接调用业务层与路由处理函数，不依赖额外测试依赖：
    cd backend && .venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import unittest

from app.routers.freq import get_windows, run_action
from app.routers.monitor import list_entries as list_monitor, list_pending_windows
from app.schemas import EntryPayload
from app.services.freq import FreqService
from app.services.monitor import MonitorService
from app.store import store

RULE_NO = "FREQ-31"


def rule_id() -> int:
    for row in store.rows("freq"):
        if row.get("规则编号") == RULE_NO:
            return int(row["id"])
    raise AssertionError(f"示例数据里没有 {RULE_NO}")


def act(action: str, **values):
    values["action"] = action
    return run_action(rule_id(), EntryPayload(values=values))


class FreqBudgetTest(unittest.TestCase):
    def setUp(self) -> None:
        store.reset()
        self.service = FreqService()
        self.monitor = MonitorService()

    def window_rows(self):
        return self.service.budget.windows(rule_id())

    def test_double_enable_keeps_one_window_and_one_budget(self):
        first = act("启用规则", 窗口开始="10:05:00")
        second = act("启用规则", 窗口开始="10:05:00")
        self.assertTrue(first.ok)
        self.assertTrue(second.ok)

        windows = self.window_rows()
        self.assertEqual(len(windows), 1, "重复启用不得新增窗口额度")
        window = windows[0]
        self.assertEqual(window["峰值额度"], 18)
        self.assertEqual(window["额度总量"], 18)
        self.assertEqual(window["规则编号"], RULE_NO)
        self.assertEqual(window["占用时间"], "10:05:00")
        self.assertEqual(window["启用次数"], 2)

        # 两次启用后的额度总量、规则编号、占用时间仍是同一份记录。
        self.assertEqual(second.entry["峰值额度"], 18)
        self.assertEqual(second.entry["规则编号"], RULE_NO)
        self.assertEqual(second.entry["占用时间"], "10:05:00")
        self.assertEqual(second.entry["窗口编号"], first.entry["窗口编号"])
        self.assertEqual(second.entry["占用版本"], first.entry["占用版本"])

    def test_rule_page_and_monitor_share_occupancy_version(self):
        act("启用规则", 窗口开始="10:05:00")
        act("启用规则", 窗口开始="10:05:00")
        act("规则换版", 每秒上限="9")

        payload = get_windows(rule_id())
        detail = self.service.get_entry(rule_id())
        pending = list_pending_windows()["items"]

        self.assertEqual(payload["占用版本"], detail["占用版本"])
        self.assertEqual(payload["窗口参数"], detail["窗口参数"])
        self.assertEqual(payload["占用记录"], detail["占用记录"])
        self.assertEqual(payload["拒绝依据"], detail["拒绝依据"])

        self.assertEqual(len(pending), 1)
        entry = pending[0]
        self.assertEqual(entry["占用版本"], payload["占用版本"])
        self.assertEqual(entry["规则版本"], payload["占用记录"]["规则版本"])
        self.assertEqual(entry["窗口编号"], payload["占用记录"]["窗口编号"])
        self.assertEqual(entry["拒绝原因"], payload["拒绝依据"]["拒绝原因"])

        # 旧窗口继续按启动时固定的规则版本结算，新参数不改写占用。
        self.assertEqual(payload["占用记录"]["规则版本"], 1)
        self.assertEqual(payload["占用记录"]["峰值额度"], 18)
        self.assertEqual(detail["规则版本"], 2)

        monitor_items = list_monitor(keyword=None, status=None, page=1, size=200).items
        in_list = [row for row in monitor_items if row.get("来源") == "freq_window"]
        self.assertEqual(len(in_list), 1)
        self.assertEqual(in_list[0]["占用版本"], payload["占用版本"])

    def test_late_correction_on_ended_window_only_records_conflict(self):
        act("启用规则", 窗口开始="10:05:00")
        act("停用规则", 窗口结束="10:06:00")
        before = self.service.get_entry(rule_id())
        result = act("迟到更正", 校正额度="3")
        after = self.service.get_entry(rule_id())

        self.assertTrue(result.ok)
        self.assertEqual(len(self.window_rows()), 1, "迟到更正不得产生第二套判定")
        self.assertEqual(after["占用记录"]["窗口编号"], before["占用记录"]["窗口编号"])
        self.assertEqual(after["占用记录"]["规则版本"], before["占用记录"]["规则版本"])
        self.assertEqual(after["占用记录"]["额度总量"], before["占用记录"]["额度总量"])
        self.assertEqual(after["占用记录"]["状态"], "已结束")
        self.assertIn("迟到样本更正命中已经结束的窗口", after["异常原因"])
        self.assertEqual(after["拒绝量"], 3)
        self.assertIn("原判定", after["拒绝原因"])

        pending = list_pending_windows()["items"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["异常原因"], "迟到样本更正命中已经结束的窗口")
        self.assertEqual(pending[0]["占用版本"], after["占用版本"])

    def test_unknown_action_is_rejected(self):
        result = act("重启窗口")
        self.assertFalse(result.ok)
        self.assertIn("不属于频率控制可执行范围", result.message)


if __name__ == "__main__":
    unittest.main()
