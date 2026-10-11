import { request } from '../../utils/request'
import { getMe, logout, wxLogin, routeAfterLogin, isManagerRole } from '../../utils/auth'
import { openPrivacyContract } from '../../utils/privacy'
import { goRecordTab, goHomeTab } from '../../utils/nav'
import { cachedFetch, invalidate, readCache, KEY, TTL_DATA } from '../../utils/cache'

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
    // 首次渲染后摘掉入场动画类，避免每次回到本页都重播
    anim: 'stagger',
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

  rendered: false,
  animTimer: null as any,

  onShow() {
    this.load()
  },
  onPullDownRefresh() {
    invalidate()
    this.load().finally(() => wx.stopPullDownRefresh())
  },
  onUnload() {
    if (this.animTimer) clearTimeout(this.animTimer)
  },

  // 首屏就绪：入场动画只播一次
  markRendered() {
    if (this.rendered) return
    this.rendered = true
    this.animTimer = setTimeout(() => this.setData({ anim: '' }), 1200)
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
    const warm = readCache(KEY.me) !== null
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
        const r = await cachedFetch<Progress>(
          KEY.progress,
          TTL_DATA,
          () => request<Progress>({ url: '/progress' }),
          (fresh) =>
            this.setData({
              progress: fresh,
              percent: Math.round((fresh.completionRate || 0) * 100)
            })
        )
        const p = r.data
        this.setData({ progress: p, percent: Math.round((p.completionRate || 0) * 100) })
      } catch {
        this.setData({ progress: null, percent: 0 })
      }
    } catch (e: any) {
      const msg: string = (e && e.message) || '未登录'
      wx.showToast({ title: msg, icon: 'none' })
      // 仅 token 失效才回登录页；后端未启动等网络问题留在本页
      if (/401|未登录|登录已过期|token/i.test(msg) && !warm) {
        setTimeout(() => wx.reLaunch({ url: '/pages/login/login' }), 800)
      }
    } finally {
      this.setData({ loading: false })
      this.markRendered()
    }
  },

  // 两个身份共用同一套 tab，这里只做快捷跳转
  onGoRecord() {
    goRecordTab()
  },
  onGoHome() {
    goHomeTab()
  },
  onGoReview() {
    wx.navigateTo({ url: '/subpackages/admin/review/review' })
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
