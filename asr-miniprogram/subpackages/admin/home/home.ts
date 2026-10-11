import { request } from '../../../utils/request'
import { getMe, logout } from '../../../utils/auth'

interface PkgItem {
  pkgId: string
  name: string
  texts: number
  assignments: number
  pending: number
  params: any
  createdBy: string
}

const ROLE_TEXT: Record<string, string> = {
  admin: '管理员',
  reviewer: '审核员',
  collector: '采集员'
}

// 管理台首页：管理员登录后的落地页，聚合「导入任务」「录音审核」与任务包概览
Page({
  data: {
    role: '',
    roleText: '',
    userId: '',
    isAdmin: false, // 仅 admin 可导入任务（reviewer 只有审核权限）
    loading: true,
    pkgs: [] as PkgItem[],
    totalAudios: 0,
    pendingAudios: 0
  },
  onShow() {
    this.load()
  },
  onPullDownRefresh() {
    this.load()
  },
  async load() {
    this.setData({ loading: true })
    try {
      const me = await getMe()
      this.setData({
        role: me.role,
        roleText: ROLE_TEXT[me.role] || me.role,
        userId: me.userId,
        isAdmin: me.role === 'admin'
      })
      const pkgRes = await request<{ list: PkgItem[] }>({ url: '/admin/packages' })
      this.setData({ pkgs: pkgRes.list || [] })
      // 审核统计（reviewer 亦可读），失败不阻塞首页
      try {
        const audios = await request<{ list: any[] }>({ url: '/admin/audios' })
        const list = audios.list || []
        this.setData({
          totalAudios: list.length,
          pendingAudios: list.filter((a) => a.status === 'uploaded').length
        })
      } catch {}
    } catch (e: any) {
      wx.showToast({ title: e.message || '加载失败', icon: 'none' })
    } finally {
      this.setData({ loading: false })
      wx.stopPullDownRefresh()
    }
  },
  onImport() {
    wx.navigateTo({ url: '/subpackages/admin/import/import' })
  },
  onReview() {
    wx.navigateTo({ url: '/subpackages/admin/review/review' })
  },
  onLogout() {
    wx.showModal({
      title: '退出登录',
      content: '确认退出当前账号？',
      success: (r) => {
        if (!r.confirm) return
        logout()
        wx.reLaunch({ url: '/pages/login/login' })
      }
    })
  }
})
