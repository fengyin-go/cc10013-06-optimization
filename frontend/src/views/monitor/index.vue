<template>
  <section class="page" data-module="monitor">
    <header class="page-head">
      <div>
        <h2>采集监控管理</h2>
        <p class="page-desc">
          维护采集监控指标的输入、执行约束与结果记录。频率预算数据集的异常窗口会进入下方待处理清单，
          占用版本与频率规则页读取的是同一份。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记监控指标</button>
        <button class="btn" type="button" @click="exportRows">导出采集监控清单</button>
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
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in baseRows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
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
        <tr v-if="!baseRows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无采集监控数据，可先登记监控指标</td>
        </tr>
      </tbody>
    </table>

    <section class="pending-panel">
      <header class="panel-head">
        <h3>频率监控待处理清单</h3>
        <span class="badge">{{ pending.length }} 个异常窗口</span>
        <button class="btn ghost" type="button" @click="reloadPending">刷新占用版本</button>
      </header>
      <p class="panel-note">接收频率预算数据集的窗口结果；每条窗口只保留一套判定，旧规则窗口按启动时固定的规则版本结算。</p>
      <table class="data-table compact">
        <thead>
          <tr>
            <th>窗口编号</th>
            <th>规则编号</th>
            <th>规则版本</th>
            <th>占用版本</th>
            <th>占用时间</th>
            <th>峰值额度</th>
            <th>异常原因</th>
            <th>拒绝依据</th>
            <th>拒绝量</th>
            <th>优先级判定</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in pending" :key="String(row.id)">
            <td>{{ row.窗口编号 }}</td>
            <td>{{ row.规则编号 }}</td>
            <td>v{{ row.规则版本 }}</td>
            <td>{{ row.占用版本 }}</td>
            <td>{{ row.占用时间 }}</td>
            <td>{{ row.峰值额度 }}</td>
            <td>{{ row.异常原因 }}</td>
            <td>{{ row.拒绝原因 }}</td>
            <td>{{ row.拒绝量 }}</td>
            <td>{{ row.优先级判定 }}</td>
          </tr>
          <tr v-if="!pending.length">
            <td colspan="10" class="empty-state">暂无待处理的频率预算窗口</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条采集监控记录</span>
      <span v-if="message" class="ok-text">{{ message }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null | boolean>
type PendingWindow = {
  id: string
  窗口编号: string
  规则编号: string
  规则版本: number
  占用版本: number
  占用时间: string
  峰值额度: number
  异常原因: string
  拒绝原因: string
  拒绝量: number
  优先级判定: string
}

const ENDPOINT = '/api/monitor'
const columns = ["指标编号", "关联端点", "成功率阈值", "延迟阈值", "错误率告警", "检测频率", "通知渠道", "静默分钟"]
const actions = ["提交校验", "启用监控", "停用监控"]
const statuses = ["草稿", "待校验", "已启用", "已停用"]
const stats = ref([{"label": "监控指标总数", "value": 0}, {"label": "已启用指标", "value": 0}, {"label": "待校验指标", "value": 0}])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const message = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const pending = ref<PendingWindow[]>([])

const baseRows = computed(() => rows.value.filter((row) => row.来源 !== 'freq_window'))

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '监控指标登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  message.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '采集监控动作未生效，请稍后重试')
    }
    message.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集监控操作失败'
  }
}

async function reloadPending() {
  try {
    const response = await request(`${ENDPOINT}/pending`)
    if (!response.ok) throw new Error('频率监控待处理清单读取失败')
    const payload = await response.json()
    pending.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '频率监控待处理清单读取失败'
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
      throw new Error('监控指标列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    refreshStats(baseRows.value)
    await reloadPending()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集监控列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.pending-panel {
  margin-top: 16px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
}
.panel-head { display: flex; align-items: center; gap: 10px; }
.panel-head h3 { margin: 0; font-size: 15px; }
.panel-head .btn { margin-left: auto; }
.badge { background: #fff4ed; color: #b54708; border-radius: 999px; padding: 2px 10px; font-size: 12px; }
.panel-note { color: var(--muted); font-size: 12px; }
.ok-text { color: #067647; }
.data-table.compact { margin-top: 8px; }
</style>
