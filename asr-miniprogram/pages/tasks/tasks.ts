import { request } from '../../utils/request'
import { getMe } from '../../utils/auth'

interface TaskItem {
  id: string
  text: string
  status: string
  version: number
  rejectReason: string | null
}

const STATUS_TEXT: Record<string, string> = {
  pending: '待领取',
  claimed: '待录制',
  uploading: '上传中',
  uploaded: '待审核',
  approved: '已通过',
  rejected: '已退回'
}

// 采集页：普通用户登录后的主界面
// 「我的任务」来自管理员导入时直接分配给本人；「公共池」为未分配任务，可自行领取
Page({
  data: {
    tasks: [] as TaskItem[],
    pool: [] as TaskItem[],
    loading: true,
    canManage: false, // 是否为 admin / reviewer，决定是否展示管理台入口
    statusText: STATUS_TEXT,
    claiming: '' as string
  },
  onShow() {
    this.refresh()
    this.loadRole()
  },
  onPullDownRefresh() {
    this.refresh().finally(() => wx.stopPullDownRefresh())
  },
  refresh() {
    return Promise.all([this.loadTasks(), this.loadPool()])
  },
  async loadTasks() {
    this.setData({ loading: true })
    try {
      const res = await request<{ list: TaskItem[] }>({ url: '/tasks' })
      this.setData({ tasks: res.list || [] })
    } catch (e: any) {
      wx.showToast({ title: e.message || '加载失败', icon: 'none' })
    } finally {
      this.setData({ loading: false })
    }
  },
  async loadPool() {
    try {
      const res = await request<{ list: TaskItem[] }>({ url: '/tasks/pool' })
      this.setData({ pool: res.list || [] })
    } catch {
      this.setData({ pool: [] })
    }
  },
  async loadRole() {
    try {
      const me = await getMe()
      const canManage = me.role === 'admin' || me.role === 'reviewer'
      this.setData({ canManage })
    } catch {
      this.setData({ canManage: false })
    }
  },
  onTapTask(e: any) {
    const id = e.currentTarget.dataset.id
    const text = e.currentTarget.dataset.text
    const version = e.currentTarget.dataset.version || 0
    wx.navigateTo({
      url: `/pages/record/record?taskId=${id}&text=${encodeURIComponent(
        text
      )}&version=${version}`
    })
  },
  // 领取公共池任务：后端乐观锁，抢领失败会返回 claimed=false
  async onClaim(e: any) {
    const id = e.currentTarget.dataset.id as string
    this.setData({ claiming: id })
    try {
      const res = await request<{ claimed: boolean }>({
        url: `/tasks/${id}/claim`,
        method: 'POST'
      })
      if (res.claimed) {
        wx.showToast({ title: '已领取', icon: 'success' })
      } else {
        wx.showToast({ title: '该任务已被领取', icon: 'none' })
      }
      await this.refresh()
    } catch (e: any) {
      wx.showToast({ title: e.message || '领取失败', icon: 'none' })
    } finally {
      this.setData({ claiming: '' })
    }
  },
  onEnterConsole() {
    wx.navigateTo({ url: '/subpackages/admin/home/home' })
  }
})
