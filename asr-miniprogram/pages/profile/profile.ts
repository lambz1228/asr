import { request } from '../../utils/request'
import { getMe, logout, wxLogin, routeAfterLogin, isManagerRole } from '../../utils/auth'
import { openPrivacyContract } from '../../utils/privacy'

// 进度口径与服务端 app/stats.py 一致：完成率 = 已通过 / 总任务数
interface Progress {
  total: number
  pending: number
  uploaded: number
  approved: number
  rejected: number
  recorded: number
  completionRate: number
}

const ROLE_TEXT: Record<string, string> = {
  admin: '管理员',
  reviewer: '审核员',
  collector: '采集员'
}

// 可切换的演示身份（后端 dev 态 DEV_MOCK_LOGIN 支持的账号）
const SWITCH_ROLES: Array<{ key: 'collector' | 'admin'; label: string }> = [
  { key: 'collector', label: '采集员（录音采集）' },
  { key: 'admin', label: '管理员（导入 / 审核）' }
]

// 个人中心：身份卡片 + 我的进度 + 功能入口 + 切换身份 / 退出登录
Page({
  data: {
    loading: true,
    userId: '',
    role: '',
    roleText: '',
    initial: '',
    isManager: false,
    isCollector: false,
    progress: null as Progress | null,
    percent: 0,
    // 仅开发版可切换演示身份（正式版不暴露）
    canSwitch: false,
    envText: '开发版',
    version: ''
  },

  onShow() {
    this.load()
  },
  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh())
  },

  readEnv() {
    let envVersion = 'develop'
    let version = ''
    try {
      const info: any = wx.getAccountInfoSync ? wx.getAccountInfoSync() : null
      envVersion = (info && info.miniProgram && info.miniProgram.envVersion) || 'develop'
      version = (info && info.miniProgram && info.miniProgram.version) || ''
    } catch {}
    const envText =
      envVersion === 'release' ? '正式版' : envVersion === 'trial' ? '体验版' : '开发版'
    this.setData({
      envText,
      version: version || '1.0.0',
      canSwitch: envVersion === 'develop' // 仅开发版允许切换演示身份
    })
  },

  async load() {
    this.setData({ loading: true })
    this.readEnv()
    try {
      const me = await getMe()
      const isManager = isManagerRole(me.role)
      this.setData({
        userId: me.userId,
        role: me.role,
        roleText: ROLE_TEXT[me.role] || me.role,
        initial: (me.userId || '?').slice(0, 1).toUpperCase(),
        isManager,
        isCollector: !isManager
      })
      if (isManager) {
        this.setData({ progress: null, percent: 0 })
        return
      }
      try {
        const p = await request<Progress>({ url: '/progress' })
        this.setData({ progress: p, percent: Math.round((p.completionRate || 0) * 100) })
      } catch {
        this.setData({ progress: null, percent: 0 })
      }
    } catch (e: any) {
      // token 失效：回登录页
      wx.showToast({ title: e.message || '未登录', icon: 'none' })
      setTimeout(() => wx.reLaunch({ url: '/pages/login/login' }), 800)
    } finally {
      this.setData({ loading: false })
    }
  },

  onGoTasks() {
    wx.reLaunch({ url: '/pages/tasks/tasks' })
  },
  onGoConsole() {
    wx.reLaunch({ url: '/subpackages/admin/home/home' })
  },
  onGoConsent() {
    wx.navigateTo({ url: '/pages/consent/consent' })
  },
  onPrivacy() {
    openPrivacyContract()
  },

  // 切换演示身份：重新以目标角色登录并按角色分流
  onSwitchRole() {
    const currentIndex = SWITCH_ROLES.findIndex((r) => r.key === this.data.role)
    wx.showActionSheet({
      itemList: SWITCH_ROLES.map(
        (r) => (r.key === this.data.role ? r.label + '（当前）' : r.label)
      ),
      success: async (res) => {
        const target = SWITCH_ROLES[res.tapIndex]
        if (!target || res.tapIndex === currentIndex) return
        wx.showLoading({ title: '切换中' })
        try {
          await wxLogin(target.key)
          await routeAfterLogin()
        } catch (e: any) {
          wx.showToast({ title: '切换失败：' + (e.message || ''), icon: 'none' })
        } finally {
          wx.hideLoading()
        }
      }
    })
  },

  onLogout() {
    wx.showModal({
      title: '退出登录',
      content: '退出后需重新登录才能继续采集。',
      confirmText: '退出',
      cancelText: '取消',
      success: (r) => {
        if (!r.confirm) return
        logout()
        wx.removeStorageSync('consentSigned')
        wx.reLaunch({ url: '/pages/login/login' })
      }
    })
  }
})
