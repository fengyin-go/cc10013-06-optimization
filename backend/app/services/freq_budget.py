"""频率预算数据集：把并发窗口的规则版本、参数快照与占用状态收在同一份结果里。

频率控制页面（规则页）和采集监控页面（待处理清单）都从这里取数，避免两边各算一套：

* 窗口启动时固定 ``规则版本``，并把当时的 ``窗口参数`` 一起快照下来；
* ``参数对象`` 与 ``占用状态`` 存在同一条窗口记录里，重复启用只更新这条记录；
* 窗口结束后迟到样本更正只能形成冲突，不能改写已经落定的判定；
* 每次真正改变占用结果时推进一次 ``占用版本``，规则页和监控清单读同一个版本号。
"""
from __future__ import annotations

import copy
import re
import threading
from datetime import datetime
from typing import Any

from app.store import store

WINDOW_MODULE = "freq_window"
RULE_MODULE = "freq"
PARAM_FIELDS = ["每秒上限", "突发容量", "冷却秒数", "队列长度", "优先级", "并发窗口"]
REVISE_ACTIONS = {"修订规则", "规则换版", "更新参数", "更新规则参数"}
CORRECTION_ACTIONS = {"迟到更正", "样本更正", "更正样本", "迟到样本更正"}
ACTIVE_STATUS = "占用中"
ENDED_STATUS = "已结束"
DEFAULT_JUDGEMENT = "每个窗口只保留一套判定：以窗口启动时固定的规则版本为准"

# 同一进程内的窗口写入串行化：连续两次启用不会各自算一份额度。
_LOCK = threading.RLock()


def _number(value: Any, default: int = 0) -> int:
    """从“18”“18/s”“上限 18”这类字段里取第一个整数，取不到时给默认值。"""
    match = re.search(r"-?\d+", str(value if value is not None else ""))
    return int(match.group()) if match else default


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _rule_version(entry: dict[str, Any]) -> int:
    try:
        return int(entry.get("规则版本", 1) or 1)
    except (TypeError, ValueError):
        return 1


def _params(entry: dict[str, Any]) -> dict[str, Any]:
    return {field: entry.get(field) for field in PARAM_FIELDS}


class FreqBudgetService:
    """频率预算数据集的读写入口；规则页与监控待处理清单共用。"""

    # ---- 读取 ---------------------------------------------------------
    def windows(self, rule_id: int | None = None) -> list[dict[str, Any]]:
        rows = store.rows(WINDOW_MODULE)
        if rule_id is not None:
            rows = [row for row in rows if int(row.get("规则ID", 0)) == rule_id]
        return sorted(rows, key=lambda row: int(row.get("id", 0)))

    def find_window(self, *, window_no: str | None = None, rule_id: int | None = None,
                    window_start: str | None = None) -> dict[str, Any] | None:
        for window in reversed(self.windows(rule_id)):
            if window_no and str(window.get("窗口编号")) == str(window_no):
                return window
            if window_start and str(window.get("窗口开始")) == str(window_start):
                return window
        return None

    def latest_window(self, rule_id: int) -> dict[str, Any] | None:
        windows = self.windows(rule_id)
        return windows[-1] if windows else None

    def active_window(self, rule_id: int) -> dict[str, Any] | None:
        for window in reversed(self.windows(rule_id)):
            if window.get("状态") == ACTIVE_STATUS:
                return window
        return None

    def enrich(self, entry: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
        """把窗口占用结果挂到规则行上；两个页面都按这一份结果展示。"""
        entry.setdefault("规则版本", 1)
        windows = self.windows(int(entry.get("id", 0)))
        latest = windows[-1] if windows else None
        if latest is not None:
            entry["窗口编号"] = latest.get("窗口编号")
            entry["占用版本"] = latest.get("占用版本", 0)
            entry["额度总量"] = latest.get("额度总量", 0)
            entry["峰值额度"] = latest.get("峰值额度", 0)
            entry["已占用额度"] = latest.get("已占用额度", 0)
            entry["占用时间"] = latest.get("占用时间", "")
            entry["窗口状态"] = latest.get("状态", "")
            entry["拒绝原因"] = latest.get("拒绝原因", "")
            entry["拒绝量"] = latest.get("拒绝量", 0)
            entry["判定"] = latest.get("判定", DEFAULT_JUDGEMENT)
            entry["异常原因"] = latest.get("异常原因", "")
            entry["待确认"] = bool(latest.get("待确认"))
            if detail:
                entry["窗口参数"] = copy.deepcopy(latest.get("窗口参数") or {})
                entry["占用记录"] = copy.deepcopy(latest)
                entry["窗口"] = [copy.deepcopy(window) for window in windows]
                entry["拒绝依据"] = {
                    "窗口编号": latest.get("窗口编号"),
                    "规则版本": latest.get("规则版本"),
                    "占用版本": latest.get("占用版本"),
                    "拒绝原因": latest.get("拒绝原因", ""),
                    "拒绝量": latest.get("拒绝量", 0),
                }
        else:
            entry.setdefault("占用版本", 0)
            entry.setdefault("额度总量", 0)
            entry.setdefault("峰值额度", 0)
            entry.setdefault("已占用额度", 0)
            entry.setdefault("占用时间", "")
            entry.setdefault("窗口状态", "未启用")
            entry.setdefault("拒绝原因", "")
            entry.setdefault("拒绝量", 0)
            entry.setdefault("判定", DEFAULT_JUDGEMENT)
            if detail:
                entry["窗口参数"] = {}
                entry["占用记录"] = None
                entry["窗口"] = []
                entry["拒绝依据"] = {}
        return entry

    def pending_windows(self) -> list[dict[str, Any]]:
        """异常窗口进入频率监控待处理清单。"""
        rows: list[dict[str, Any]] = []
        rules = {int(row.get("id", 0)): row for row in store.rows(RULE_MODULE)}
        for window in self.windows():
            if not (window.get("异常") or window.get("冲突") or window.get("待确认")):
                continue
            rule = rules.get(int(window.get("规则ID", 0)), {})
            rows.append({
                "id": f"freq-window-{window.get('id')}",
                "status": "待处理",
                "pending": True,
                "abnormal": True,
                "指标编号": window.get("窗口编号"),
                "关联端点": rule.get("目标端点", ""),
                "成功率阈值": "—",
                "延迟阈值": "—",
                "错误率告警": window.get("异常原因") or "频率预算窗口异常",
                "检测频率": "窗口结果落库时",
                "通知渠道": "监控待处理清单",
                "静默分钟": "",
                "来源": "freq_window",
                "来源模块": "频率控制",
                "窗口编号": window.get("窗口编号"),
                "规则编号": window.get("规则编号"),
                "规则版本": window.get("规则版本"),
                "占用版本": window.get("占用版本"),
                "占用时间": window.get("占用时间"),
                "额度总量": window.get("额度总量"),
                "峰值额度": window.get("峰值额度"),
                "拒绝原因": window.get("拒绝原因"),
                "拒绝量": window.get("拒绝量", 0),
                "异常原因": window.get("异常原因", ""),
                "冲突": window.get("冲突", ""),
                "判定": window.get("判定", DEFAULT_JUDGEMENT),
                "优先级判定": window.get("优先级判定", ""),
            })
        return rows

    # ---- 写入 ---------------------------------------------------------
    def enable(self, entry: dict[str, Any], values: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        with _LOCK:
            return self._enable(entry, values)

    def _enable(self, entry: dict[str, Any], values: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        """启用规则：同一窗口重复启用只更新原占用，不另起额度。"""
        values = values or {}
        requested_no = str(values.get("窗口编号") or "").strip()
        requested_start = str(
            values.get("窗口开始") or values.get("占用时间") or values.get("启用时间") or ""
        ).strip()

        existing = None
        if requested_no:
            existing = self.find_window(window_no=requested_no, rule_id=int(entry.get("id", 0)))
        if existing is None:
            existing = self.active_window(int(entry.get("id", 0)))
        if existing is None and requested_start:
            existing = self.find_window(
                rule_id=int(entry.get("id", 0)), window_start=requested_start
            )

        if existing is not None:
            # 第二次启用：只更新这一条窗口记录，额度、规则编号、占用时间保持同一份。
            existing["启用次数"] = int(existing.get("启用次数", 1)) + 1
            existing["最近启用时间"] = requested_start or _now()
            note = (
                f"重复启用沿用窗口 {existing.get('窗口编号')}，"
                f"额度总量与峰值额度保持 {existing.get('峰值额度')}，未新增额度"
            )
            existing.setdefault("更新记录", []).append(note)
            self._touch_rule(entry, existing)
            return entry, note

        start = requested_start or _now()
        version = store.bump_version(RULE_MODULE)
        params = _params(entry)
        peak = _number(entry.get("每秒上限"))
        window = {
            "id": max((int(row.get("id", 0)) for row in store.rows(WINDOW_MODULE)), default=0) + 1,
            "窗口编号": requested_no or f"{entry.get('规则编号')}-W{version:02d}",
            "规则ID": int(entry.get("id", 0)),
            "规则编号": entry.get("规则编号"),
            "规则版本": _rule_version(entry),
            "窗口参数": params,
            "参数对象": copy.deepcopy(params),
            "额度总量": peak,
            "峰值额度": peak,
            "已占用额度": peak,
            "窗口开始": start,
            "窗口结束": "",
            "占用时间": start,
            "状态": ACTIVE_STATUS,
            "占用版本": version,
            "启用次数": 1,
            "最近启用时间": start,
            "拒绝原因": (
                f"规则版本 v{_rule_version(entry)} 的窗口按启动时额度 {peak} 判定，"
                "超出部分拒绝"
            ),
            "拒绝量": 0,
            "异常": False,
            "待确认": False,
            "异常原因": "",
            "冲突": "",
            "判定": DEFAULT_JUDGEMENT,
            "优先级判定": "窗口启动时固定的规则版本优先于当前规则参数",
            "更新记录": [
                f"窗口启动并固定规则版本 v{_rule_version(entry)}，峰值额度 {peak}"
            ],
        }
        window["占用状态"] = self._occupancy(window)
        store.rows(WINDOW_MODULE).append(window)
        entry["status"] = "已启用"
        entry["pending"] = False
        entry["abnormal"] = False
        self._touch_rule(entry, window)
        return entry, (
            f"频率规则已启用，窗口 {window['窗口编号']} 固定规则版本 v{window['规则版本']}，"
            f"峰值额度 {peak}"
        )

    def close(self, entry: dict[str, Any], values: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        with _LOCK:
            return self._close(entry, values)

    def _close(self, entry: dict[str, Any], values: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        """停用规则：结束当前窗口，拒绝依据随窗口一起保留。"""
        values = values or {}
        window = self.active_window(int(entry.get("id", 0)))
        entry["status"] = "已停用"
        entry["pending"] = False
        entry["abnormal"] = True
        if window is None:
            return entry, "频率规则已停用，当前没有进行中的并发窗口"
        window["状态"] = ENDED_STATUS
        window["窗口结束"] = str(values.get("窗口结束") or values.get("停用时间") or _now())
        window["占用版本"] = store.bump_version(RULE_MODULE)
        window["拒绝原因"] = str(
            values.get("拒绝原因") or window.get("拒绝原因")
            or f"规则版本 v{window.get('规则版本')} 的窗口已结束，后续请求按该版本拒绝"
        )
        window["占用状态"] = self._occupancy(window)
        window.setdefault("更新记录", []).append(
            f"窗口在 {window['窗口结束']} 结束，保留规则版本 v{window.get('规则版本')} 的拒绝依据"
        )
        self._touch_rule(entry, window)
        return entry, f"频率规则已停用，窗口 {window['窗口编号']} 已结束并保留原判定"

    def revise(self, entry: dict[str, Any], values: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        with _LOCK:
            return self._revise(entry, values)

    def _revise(self, entry: dict[str, Any], values: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        """规则换版：只影响之后的窗口，旧窗口继续按启动时固定的版本结算。"""
        values = values or {}
        new_version = _rule_version(entry) + 1
        entry["规则版本"] = new_version
        for field in PARAM_FIELDS:
            if field in values and values.get(field) not in (None, ""):
                entry[field] = values.get(field)
        entry["参数版本历史"] = list(entry.get("参数版本历史") or []) + [
            {"规则版本": new_version, "参数对象": _params(entry)}
        ]

        active = self.active_window(int(entry.get("id", 0)))
        message = f"频率规则已换版到 v{new_version}，新参数只作用于之后启动的窗口"
        if active is not None and int(active.get("规则版本", 0)) != new_version:
            active["占用版本"] = store.bump_version(RULE_MODULE)
            active["异常"] = True
            active["待确认"] = True
            active["异常原因"] = "旧规则窗口与新参数相遇"
            active["冲突"] = "旧规则窗口与新参数相遇"
            active["优先级判定"] = "窗口启动时固定的规则版本优先，旧窗口占用记录作为有效终态"
            active["判定"] = (
                f"窗口 {active.get('窗口编号')} 仍按启动时固定的规则版本 "
                f"v{active.get('规则版本')} 结算；v{new_version} 的新参数不回溯改写占用"
            )
            active.setdefault("更新记录", []).append(
                f"规则换版到 v{new_version}，窗口保持 v{active.get('规则版本')} 的占用与拒绝口径"
            )
            message += "；旧窗口保留原占用记录并转入监控待处理清单"
        self.enrich(entry)
        return entry, message

    def apply_correction(self, entry: dict[str, Any], values: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        with _LOCK:
            return self._apply_correction(entry, values)

    def _apply_correction(self, entry: dict[str, Any], values: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        """迟到样本更正：命中已结束窗口时只形成冲突，不改写唯一判定。"""
        values = values or {}
        rule_id = int(entry.get("id", 0))
        window_no = str(values.get("窗口编号") or "").strip() or None
        window = self.find_window(window_no=window_no, rule_id=rule_id) if window_no else None
        if window is None:
            window = self.active_window(rule_id) or self.latest_window(rule_id)
        if window is None:
            return entry, "当前规则没有可更正的并发窗口"

        amount = _number(values.get("校正额度") or values.get("更正量") or values.get("额度"), 1)
        if window.get("状态") == ENDED_STATUS:
            # 已结束窗口的判定已经落定：迟到更正只登记冲突，不产生第二套判定。
            window["占用版本"] = store.bump_version(RULE_MODULE)
            window["冲突"] = "迟到样本更正命中已经结束的窗口"
            window["异常"] = True
            window["待确认"] = True
            window["异常原因"] = window["冲突"]
            window["优先级判定"] = "已结束窗口以窗口启动时固定的规则版本为有效终态"
            window["拒绝量"] = int(window.get("拒绝量", 0) or 0) + max(amount, 0)
            window["拒绝原因"] = (
                f"迟到更正命中已结束窗口 {window.get('窗口编号')}，"
                f"保留规则版本 v{window.get('规则版本')} 的原判定，更正额度 {amount} 转入拒绝量"
            )
            window.setdefault("更新记录", []).append(
                f"迟到更正命中已结束窗口（占用版本 {window.get('占用版本')}），仅登记冲突，判定不变"
            )
            window["占用状态"] = self._occupancy(window)
            self._touch_rule(entry, window)
            return entry, "迟到更正命中已结束窗口，已登记冲突并转入监控待处理清单，原判定保留"

        window["已占用额度"] = max(0, int(window.get("已占用额度", 0) or 0) + amount)
        window["峰值额度"] = max(int(window.get("峰值额度", 0) or 0), int(window.get("已占用额度", 0) or 0))
        window["占用版本"] = store.bump_version(RULE_MODULE)
        window["占用状态"] = self._occupancy(window)
        window.setdefault("更新记录", []).append(
            f"窗口内样本更正 {amount}，占用版本推进到 {window['占用版本']}"
        )
        self._touch_rule(entry, window)
        return entry, f"样本更正已并入窗口 {window.get('窗口编号')}，未新增窗口"

    # ---- 内部 ---------------------------------------------------------
    @staticmethod
    def _occupancy(window: dict[str, Any]) -> dict[str, Any]:
        return {
            "额度总量": window.get("额度总量", 0),
            "峰值额度": window.get("峰值额度", 0),
            "已占用额度": window.get("已占用额度", 0),
            "占用时间": window.get("占用时间", ""),
            "状态": window.get("状态", ""),
            "拒绝量": window.get("拒绝量", 0),
            "拒绝原因": window.get("拒绝原因", ""),
        }

    @staticmethod
    def _touch_rule(entry: dict[str, Any], window: dict[str, Any]) -> None:
        """把窗口结果同步回规则行，规则页无需另算一份。"""
        entry["窗口编号"] = window.get("窗口编号")
        entry["占用版本"] = window.get("占用版本", 0)
        entry["额度总量"] = window.get("额度总量", 0)
        entry["峰值额度"] = window.get("峰值额度", 0)
        entry["已占用额度"] = window.get("已占用额度", 0)
        entry["占用时间"] = window.get("占用时间", "")
        entry["窗口状态"] = window.get("状态", "")
        entry["拒绝原因"] = window.get("拒绝原因", "")
        entry["拒绝量"] = window.get("拒绝量", 0)
        entry["判定"] = window.get("判定", DEFAULT_JUDGEMENT)
        entry["异常原因"] = window.get("异常原因", "")
        entry["待确认"] = bool(window.get("待确认"))
        entry["abnormal"] = bool(window.get("异常")) or entry.get("status") == "已停用"
