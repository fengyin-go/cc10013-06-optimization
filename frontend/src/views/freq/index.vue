<template>
  <section class="page" data-module="freq">
    <header class="page-head">
      <div>
        <h2>频率控制管理</h2>
        <p class="page-desc">
          维护频率控制规则与并发窗口。窗口启动时固定规则版本，参数对象与占用状态作为同一份结果保存，
          重复启用只更新现有窗口，不另起额度。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记频率规则</button>
        <button class="btn" type="button" @click="exportRows">导出频率控制清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>窗口开始</span>
        <input v-model="windowStart" placeholder="如 10:05:00" />
      </label>
      <label class="filter-item">
        <span>校正额度</span>
        <input v-model="correction" placeholder="迟到更正额度" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>规则版本</th>
          <th>窗口编号</th>
          <th>额度总量</th>
          <th>峰值额度</th>
          <th>占用时间</th>
          <th>占用版本</th>
          <th>窗口状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="String(row.id)"
          :class="{ 'row-active': String(row.id) === selectedId }"
        >
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.规则版本 ?? '—' }}</td>
          <td>{{ row.窗口编号 ?? '—' }}</td>
          <td>{{ row.额度总量 ?? '—' }}</td>
          <td>{{ row.峰值额度 ?? '—' }}</td>
          <td>{{ row.占用时间 ?? '—' }}</td>
          <td>{{ row.占用版本 ?? '—' }}</td>
          <td>{{ row.窗口状态 ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="inspect(row)">查看窗口</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 9" class="empty-state">暂无频率控制数据，可先登记频率规则</td>
        </tr>
      </tbody>
    </table>

    <section v-if="detail" class="detail-panel">
      <header class="panel-head">
        <h3>频率预算数据集 · {{ detail.规则编号 }}</h3>
        <span class="badge">占用版本 {{ detail.占用版本 }}</span>
        <span class="badge">规则版本 v{{ detail.占用记录?.规则版本 ?? '—' }}</span>
        <button class="btn ghost" type="button" @click="detail = null">收起</button>
      </header>
      <p class="panel-note">{{ detail.判定 }}</p>
      <div class="panel-grid">
        <div>
          <h4>窗口参数（启动时快照）</h4>
          <dl class="kv">
            <template v-for="field in paramFields" :key="field">
              <dt>{{ field }}</dt>
              <dd>{{ detail.窗口参数?.[field] ?? '—' }}</dd>
            </template>
          </dl>
        </div>
        <div>
          <h4>占用记录</h4>
          <dl class="kv">
            <dt>窗口编号</dt><dd>{{ detail.占用记录?.窗口编号 ?? '—' }}</dd>
            <dt>规则编号</dt><dd>{{ detail.占用记录?.规则编号 ?? '—' }}</dd>
            <dt>占用时间</dt><dd>{{ detail.占用记录?.占用时间 ?? '—' }}</dd>
            <dt>额度总量</dt><dd>{{ detail.占用记录?.额度总量 ?? '—' }}</dd>
            <dt>峰值额度</dt><dd>{{ detail.占用记录?.峰值额度 ?? '—' }}</dd>
            <dt>已占用额度</dt><dd>{{ detail.占用记录?.已占用额度 ?? '—' }}</dd>
            <dt>启用次数</dt><dd>{{ detail.占用记录?.启用次数 ?? '—' }}</dd>
            <dt>占用版本</dt><dd>{{ detail.占用记录?.占用版本 ?? '—' }}</dd>
            <dt>窗口状态</dt><dd>{{ detail.占用记录?.状态 ?? '—' }}</dd>
          </dl>
        </div>
        <div>
          <h4>拒绝依据</h4>
          <dl class="kv">
            <dt>窗口编号</dt><dd>{{ detail.拒绝依据?.窗口编号 ?? '—' }}</dd>
            <dt>规则版本</dt><dd>v{{ detail.拒绝依据?.规则版本 ?? '—' }}</dd>
            <dt>占用版本</dt><dd>{{ detail.拒绝依据?.占用版本 ?? '—' }}</dd>
            <dt>拒绝量</dt><dd>{{ detail.拒绝依据?.拒绝量 ?? 0 }}</dd>
          </dl>
          <p class="panel-note">{{ detail.拒绝依据?.拒绝原因 || '—' }}</p>
        </div>
      </div>
      <p v-if="detail.异常原因" class="warn-text">异常：{{ detail.异常原因 }}</p>
      <table v-if="(detail.窗口?.length ?? 0) > 1" class="data-table compact">
        <thead>
          <tr><th>窗口编号</th><th>规则版本</th><th>占用时间</th><th>峰值额度</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="window in detail.窗口" :key="String(window.窗口编号)">
            <td>{{ window.窗口编号 }}</td>
            <td>v{{ window.规则版本 }}</td>
            <td>{{ window.占用时间 }}</td>
            <td>{{ window.峰值额度 }}</td>
            <td>{{ window.状态 }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条频率控制记录</span>
      <span v-if="message" class="ok-text">{{ message }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null | boolean>
type WindowDetail = {
  规则编号: string
  规则版本: number
  占用版本: number
  窗口参数: Record<string, string | number | null>
  占用记录: Record<string, unknown> | null
  拒绝依据: Record<string, string | number | null>
  判定: string
  异常原因?: string
  窗口?: Record<string, unknown>[]
}

const ENDPOINT = '/api/freq'
const columns = ["规则编号", "目标端点", "每秒上限", "突发容量", "冷却秒数", "队列长度", "优先级", "并发窗口"]
const paramFields = ["每秒上限", "突发容量", "冷却秒数", "队列长度", "优先级", "并发窗口"]
const actions = ["提交校验", "启用规则", "停用规则", "规则换版", "迟到更正"]
const statuses = ["草稿", "待校验", "已启用", "已停用"]
const stats = ref([{"label": "频率规则总数", "value": 0}, {"label": "已启用规则", "value": 0}, {"label": "待校验规则", "value": 0}])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const message = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const windowStart = ref('')
const correction = ref('')
const detail = ref<WindowDetail | null>(null)
const selectedId = ref<string | null>(null)

function resetFilters() {
  filters.value = {}
  windowStart.value = ''
  correction.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '频率规则登记入口尚未接入审批流'
}

function actionPayload(action: string) {
  const values: Record<string, string> = { action }
  if (windowStart.value.trim()) values.窗口开始 = windowStart.value.trim()
  if (correction.value.trim()) values.校正额度 = correction.value.trim()
  if (action === '规则换版') {
    values.每秒上限 = correction.value.trim() || String(detail.value?.窗口参数?.['每秒上限'] ?? '9')
  }
  return values
}

async function inspect(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/windows`)
    if (!response.ok) throw new Error('频率预算数据集读取失败')
    detail.value = (await response.json()) as WindowDetail
    selectedId.value = String(row.id)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '频率预算数据集读取失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  message.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: actionPayload(action) }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '频率控制动作未生效，请稍后重试')
    }
    message.value = payload.message
    await reload()
    await inspect({ id: row.id })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '频率控制操作失败'
  }
}

function refreshStats(items: Row[]) {
  stats.value[0].value = items.length
  stats.value[1].value = items.filter((row) => row.status === '已启用').length
  stats.value[2].value = items.filter((row) => row.status === '待校验').length
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('频率规则列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    refreshStats(rows.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '频率控制列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.row-active { background: #eef4ff; }
.detail-panel {
  margin-top: 14px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
}
.panel-head { display: flex; align-items: center; gap: 10px; }
.panel-head h3 { margin: 0; font-size: 15px; }
.panel-head .btn { margin-left: auto; }
.badge { background: #eef4ff; color: var(--brand); border-radius: 999px; padding: 2px 10px; font-size: 12px; }
.panel-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.panel-grid h4 { margin: 10px 0 6px; font-size: 13px; }
.kv { display: grid; grid-template-columns: auto 1fr; gap: 4px 10px; margin: 0; font-size: 12px; }
.kv dt { color: var(--muted); }
.kv dd { margin: 0; }
.panel-note { color: var(--muted); font-size: 12px; }
.warn-text { color: #b54708; font-size: 12px; }
.ok-text { color: #067647; }
.data-table.compact { margin-top: 10px; }
</style>
