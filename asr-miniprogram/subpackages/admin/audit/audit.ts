import { request } from '../../../utils/request'

// 后端 AuditLog 记录（/api/admin/audit-logs）
interface LogItem {
  id: number
  operatorId: string
  operatorRole: string
  action: string
  targetType: string
  targetId: string
  detail: any
  ip: string
  createdAt: string
  // 渲染用（后端返回后本地补全）
  actionText?: string
  roleText?: string
  timeText?: string
  detailText?: string
}

const ACTION_TEXT: Record<string, string> = {
  export: '导出数据集',
  export_async_start: '发起异步导出',
  export_cleanup: '清理过期导出',
  review: '审核录音',
  set_role: '调整角色',
  import_package: '导入任务包'
}
const ROLE_TEXT: Record<string, string> = {
  admin: '管理员',
  reviewer: '审核员',
  collector: '采集员'
}
const STATUS_TEXT: Record<string, string> = {
  done: '已完成',
  pending: '打包中',
  failed: '失败',
  expired: '已过期'
}

function fmtTime(s: string): string {
  if (!s) return ''
  return s.replace('T', ' ').slice(0, 19)
}

function normalize(x: any): LogItem {
  const detail = x.detail || {}
  const keys = Object.keys(detail)
  return {
    ...x,
    actionText: ACTION_TEXT[x.action] || x.action,
    roleText: ROLE_TEXT[x.operatorRole] || x.operatorRole,
    timeText: fmtTime(x.createdAt),
    detailText: keys.length ? keys.map((k) => `${k}=${detail[k]}`).join(' · ') : ''
  }
}

// 审计日志（方案 §9.1）：谁在什么时候对什么做了什么。仅管理员可读。
Page({
  data: {
    items: [] as LogItem[],
    total: 0,
    actions: [] as string[],
    action: '',
    limit: 30,
    offset: 0,
    hasMore: false,
    loading: true,
    loadingMore: false,
    cleaning: false,
    jobs: [] as any[],
    ttlDays: 7,
    showJobs: false,
    ACTION_TEXT,
    STATUS_TEXT
  },
  onShow() {
    this.reload()
  },
  onPullDownRefresh() {
    this.reload()
  },

  async reload() {
    this.setData({ loading: true })
    try {
      await this.fetch(0)
      await this.loadJobs()
    } catch (e: any) {
      wx.showToast({ title: e.message || '加载失败', icon: 'none' })
    } finally {
      this.setData({ loading: false })
      wx.stopPullDownRefresh()
    }
  },

  async fetch(offset: number) {
    const q = [`limit=${this.data.limit}`, `offset=${offset}`]
    if (this.data.action) q.push('action=' + encodeURIComponent(this.data.action))
    const res = await request<{ list: any[]; total: number; actions: string[] }>({
      url: '/admin/audit-logs?' + q.join('&')
    })
    const fresh = (res.list || []).map(normalize)
    const items = offset === 0 ? fresh : this.data.items.concat(fresh)
    this.setData({
      items,
      total: res.total || 0,
      actions: res.actions || [],
      offset,
      hasMore: items.length < (res.total || 0)
    })
  },

  onFilter(e: any) {
    const a = e.currentTarget.dataset.a || ''
    this.setData({ action: a })
    this.reload()
  },

  onLoadMore() {
    if (this.data.loadingMore || !this.data.hasMore) return
    this.setData({ loadingMore: true })
    this.fetch(this.data.offset + this.data.limit).finally(() =>
      this.setData({ loadingMore: false })
    )
  },

  // 导出任务列表（含留存到期时间）
  async loadJobs() {
    try {
      const res = await request<{ list: any[]; ttlDays: number }>({
        url: '/admin/export/jobs?limit=10'
      })
      const jobs = (res.list || []).map((j: any) => ({
        ...j,
        statusText: STATUS_TEXT[j.status] || j.status,
        timeText: fmtTime(j.finishedAt || j.createdAt),
        expiresText: j.expiresAt ? fmtTime(j.expiresAt).slice(0, 10) : ''
      }))
      this.setData({ jobs, ttlDays: res.ttlDays || 7 })
    } catch {}
  },
  onToggleJobs() {
    this.setData({ showJobs: !this.data.showJobs })
  },

  // 手动清理超期导出（方案 §6.2）
  async onCleanup() {
    if (this.data.cleaning) return
    const r = await new Promise<any>((resolve) =>
      wx.showModal({
        title: '清理过期导出',
        content: `将删除超过 ${this.data.ttlDays} 天的导出包，确认继续？`,
        success: resolve
      })
    )
    if (!r.confirm) return
    this.setData({ cleaning: true })
    wx.showLoading({ title: '清理中' })
    try {
      const s: any = await request({ url: '/admin/export/cleanup', method: 'POST' })
      wx.hideLoading()
      wx.showToast({
        title: `清理 ${s.expiredJobs} 个任务 / ${s.deletedFiles + s.orphans} 个文件`,
        icon: 'none'
      })
      // 清理动作本身也会写审计日志，刷新即可看到
      await this.reload()
    } catch (e: any) {
      wx.hideLoading()
      wx.showToast({ title: e.message || '清理失败', icon: 'none' })
    } finally {
      this.setData({ cleaning: false })
    }
  }
})
