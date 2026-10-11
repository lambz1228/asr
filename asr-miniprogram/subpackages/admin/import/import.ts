import { request } from '../../../utils/request'

interface ImportResult {
  pkgId: string
  name: string
  assignees: string[]
  distribute: string
  createdTexts: number
  createdAssignments: number
  skipped: number
  errors: string[]
}

interface UserItem {
  userId: string
  openid?: string | null
  role: string
  checked?: boolean
}

const DISTRIBUTE_LABELS = ['每人一份（各录全部）', '轮流分摊']
const DISTRIBUTE_VALUES = ['all', 'split']

// 导入任务：管理端批量导入待录制文本，并以子任务方式下发给采集员
// ① 粘贴多行文本（每行一条）→ JSON 提交
// ② 上传 .xlsx / .csv / .json 文件 → multipart 上传
Page({
  data: {
    mode: 'paste' as 'paste' | 'file',
    formats: ['aac', 'mp3'],
    formatIndex: 0,
    format: 'aac',
    pkgId: '',
    name: '',
    sampleRate: '16000',
    channels: '1',
    text: '',
    fileName: '',
    filePath: '',
    users: [] as UserItem[],
    selected: [] as string[],
    distributeLabels: DISTRIBUTE_LABELS,
    distributeIndex: 0,
    loading: false,
    result: null as ImportResult | null
  },
  onLoad() {
    this.loadUsers()
  },

  // 拉取可下发的采集员账号
  async loadUsers() {
    try {
      const res = await request<{ list: UserItem[] }>({ url: '/admin/users' })
      const users = (res.list || [])
        .filter((u) => u.role === 'collector')
        .map((u) => ({ ...u, checked: false }))
      this.setData({ users })
    } catch (e: any) {
      wx.showToast({ title: e.message || '采集员列表加载失败', icon: 'none' })
    }
  },
  onSelectUsers(e: any) {
    const selected: string[] = e.detail.value || []
    this.setData({
      selected,
      users: this.data.users.map((u) => ({ ...u, checked: selected.indexOf(u.userId) >= 0 }))
    })
  },
  onSelectAll() {
    this.setData({
      selected: this.data.users.map((u) => u.userId),
      users: this.data.users.map((u) => ({ ...u, checked: true }))
    })
  },
  onClearAll() {
    this.setData({
      selected: [],
      users: this.data.users.map((u) => ({ ...u, checked: false }))
    })
  },
  onDistribute(e: any) {
    this.setData({ distributeIndex: Number(e.detail.value) })
  },

  switchMode(e: any) {
    this.setData({ mode: e.currentTarget.dataset.m, result: null })
  },
  onInput(e: any) {
    const k = e.currentTarget.dataset.k
    this.setData({ [k]: e.detail.value } as any)
  },
  onFormat(e: any) {
    const i = Number(e.detail.value)
    this.setData({ formatIndex: i, format: this.data.formats[i] })
  },

  distributeValue(): string {
    return DISTRIBUTE_VALUES[this.data.distributeIndex] || 'all'
  },
  // 未选采集员 → 进入公共池，提交前给一次确认
  confirmPool(): Promise<boolean> {
    if (this.data.selected.length > 0) return Promise.resolve(true)
    return new Promise((resolve) => {
      wx.showModal({
        title: '未选择下发对象',
        content: '未勾选采集员时，任务将进入公共池，由采集员自行领取。确定继续吗？',
        confirmText: '继续',
        success: (r) => resolve(!!r.confirm),
        fail: () => resolve(false)
      })
    })
  },

  // —— 方式二：上传文件 ——
  onChooseFile() {
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['xlsx', 'xls', 'csv', 'json', 'txt'],
      success: (r) => {
        const f = r.tempFiles[0]
        this.setData({ fileName: f.name, filePath: f.path, result: null })
      },
      fail: () => {}
    })
  },
  async onSubmitFile() {
    if (!this.data.filePath) {
      wx.showToast({ title: '请先选择文件', icon: 'none' })
      return
    }
    if (!(await this.confirmPool())) return

    const app = getApp<any>()
    const token = wx.getStorageSync('token') || ''
    this.setData({ loading: true })
    wx.uploadFile({
      url: app.globalData.baseUrl + '/admin/packages/import',
      filePath: this.data.filePath,
      name: 'file',
      header: token ? { Authorization: 'Bearer ' + token } : {},
      formData: {
        pkgId: this.data.pkgId.trim(),
        name: this.data.name.trim(),
        assignees: this.data.selected.join(','),
        distribute: this.distributeValue(),
        sampleRate: this.data.sampleRate,
        channels: this.data.channels,
        format: this.data.format
      },
      success: (res) => {
        try {
          const body = JSON.parse(res.data)
          if (res.statusCode === 200 && body.code === 0) {
            this.setData({ result: body.data, filePath: '', fileName: '' })
            wx.showToast({ title: '导入成功', icon: 'success' })
          } else {
            wx.showToast({ title: (body && body.message) || 'HTTP ' + res.statusCode, icon: 'none' })
          }
        } catch {
          wx.showToast({ title: '返回解析失败', icon: 'none' })
        }
      },
      fail: (err: any) => {
        wx.showToast({ title: (err && err.errMsg) || '上传失败', icon: 'none' })
      },
      complete: () => this.setData({ loading: false })
    })
  },

  // —— 方式一：粘贴文本 ——
  async onSubmitPaste() {
    const lines = (this.data.text || '')
      .split('\n')
      .map((s) => s.trim())
      .filter((s) => s.length > 0)
    if (lines.length === 0) {
      wx.showToast({ title: '请输入至少一行文本', icon: 'none' })
      return
    }
    if (!(await this.confirmPool())) return

    const texts = lines.map((t) => ({ text: t }))
    this.setData({ loading: true })
    try {
      const res = await request<ImportResult>({
        url: '/admin/packages/import',
        method: 'POST',
        data: {
          pkgId: this.data.pkgId.trim(),
          name: this.data.name.trim(),
          assignees: this.data.selected,
          distribute: this.distributeValue(),
          params: {
            sample_rate: Number(this.data.sampleRate) || 16000,
            channels: Number(this.data.channels) || 1,
            format: this.data.format
          },
          texts
        }
      })
      this.setData({ result: res, text: '' })
      wx.showToast({ title: '导入成功', icon: 'success' })
    } catch (e: any) {
      wx.showToast({ title: e.message || '导入失败', icon: 'none' })
    } finally {
      this.setData({ loading: false })
    }
  }
})
