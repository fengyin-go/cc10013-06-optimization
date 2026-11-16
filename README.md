# API数据聚合采集中心

面向多源API接入、接口编排、数据聚合、响应校验、频率控制与数据转储的API数据聚合采集中心。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 接口管理 | `endpoint` | API端点 | 端点编号、接口地址、请求方法 |
| 接口编排 | `chain` | 调用链路 | 链路编号、端点序列、数据传递映射 |
| 频率控制 | `freq` | 频率规则 | 规则编号、目标端点、每秒上限 |
| 数据映射 | `mapper` | 映射规则 | 规则编号、源字段路径、目标字段名 |
| 响应校验 | `validator` | 校验规则 | 规则编号、关联端点、校验字段 |
| 失败重试 | `retry` | 重试策略 | 策略编号、关联端点、最大重试 |
| 数据聚合 | `aggregator` | 聚合任务 | 任务编号、输入端点列表、合并策略 |
| 凭证管理 | `auth` | 认证凭证 | 凭证编号、关联端点、认证类型 |
| 缓存策略 | `cache` | 缓存规则 | 规则编号、关联端点、缓存键模板 |
| 数据转储 | `dump` | 转储配置 | 配置编号、数据来源、存储类型 |
| 采集调度 | `schedule` | 调度计划 | 计划编号、关联链路、调度表达式 |
| 采集监控 | `monitor` | 监控指标 | 指标编号、关联端点、成功率阈值 |
| 数据转换 | `transform` | 转换脚本 | 脚本编号、输入数据源、转换表达式 |
| 数据清洗 | `cleanse` | 清洗规则 | 规则编号、目标字段、空值替换 |
| 限流配置 | `ratelimit` | 限流规则 | 规则编号、目标端点、令牌速率 |
| 采集日志 | `log` | 日志记录 | 记录编号、关联端点、请求时间 |
| 增量采集 | `delta` | 增量游标 | 游标编号、目标端点、增量字段 |
| 数据导出 | `export` | 导出通道 | 通道编号、输出数据集、目标系统 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 频率预算数据集

频率控制的并发窗口占用记录单独存在 `freq_window` 表里（`backend/app/services/freq_budget.py`），
它随频率规则一起取数，不出现在运营概览的独立模块中。

- 窗口启动时固定 `规则版本`，并把当时的 `窗口参数`（每秒上限、突发容量、冷却秒数、队列长度、
  优先级、并发窗口）快照进同一条窗口记录；`参数对象`、`占用状态`、`拒绝原因` 都出自这份结果。
- 同一规则重复启用时沿用现有窗口，只累加 `启用次数`、更新 `最近启用时间`，不新增额度；
  额度总量、规则编号、占用时间保持同一份。复测样例：`FREQ-31` 在 `10:05:00` 连续启用两次，
  峰值额度仍是 18，窗口记录只有一条。
- `规则换版` 只影响之后启动的窗口；旧窗口与新参数相遇时以窗口启动时固定的规则版本为准，
  旧占用记录作为有效终态，并作为异常窗口进入监控待处理清单。
- `迟到更正` 命中已结束窗口时只登记冲突：原判定、窗口编号、规则版本不变，更正额度计入拒绝量，
  不会产生第二套判定。
- 每次占用结果变化都推进一次 `占用版本`；规则页 `GET /api/freq/{id}/windows`、
  规则明细 `GET /api/freq/{id}`、监控待处理清单 `GET /api/monitor/pending` 读的是同一个版本号。

| 接口 | 说明 |
| --- | --- |
| `GET /api/freq/{id}/windows` | 规则页读取的窗口参数、占用记录、拒绝依据与占用版本 |
| `GET /api/monitor/pending` | 频率监控待处理清单，接收异常窗口的窗口结果 |
| `POST /api/freq/{id}/actions` | `values.action` 支持 `提交校验`、`启用规则`、`停用规则`、`规则换版`、`迟到更正` |

复测用例：`cd backend && .venv/bin/python -m unittest discover -s tests -t . -v`。

领域：数据工程
子方向：数据采集、爬虫与RPA
