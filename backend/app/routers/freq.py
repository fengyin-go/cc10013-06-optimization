"""频率控制接口：维护频率规则，覆盖提交校验、启用规则、停用规则等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.freq import FreqService

router = APIRouter(prefix="/api/freq", tags=["频率控制"])

service = FreqService()

LIST_FIELDS = ["规则编号", "目标端点", "每秒上限", "突发容量", "冷却秒数", "队列长度", "优先级", "并发窗口"]
STATUSES = ["草稿", "待校验", "已启用", "已停用"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按规则编号检索"),
    status: str | None = Query(default=None, description="草稿、待校验、已启用、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按规则编号与状态过滤频率控制列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出频率控制清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "freq", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条频率规则明细；窗口参数、占用记录与拒绝依据出自同一份占用版本。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"频率规则 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/windows")
def get_windows(entry_id: int) -> dict:
    """规则页读取的频率预算数据集：窗口参数、占用记录与拒绝依据同一份结果。"""
    payload = service.budget_windows(entry_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"频率规则 {entry_id} 不存在或已归档")
    return payload


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条频率规则，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="频率规则已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条频率规则执行校验、启用、停用、换版与更正；不允许的动作会被拦下并说明原因。"""
    values = payload.merged_values()
    action = str(values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
