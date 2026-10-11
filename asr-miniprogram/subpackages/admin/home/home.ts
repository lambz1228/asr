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
interface CollectorRow extends Progress {
  userId: string
  percent: number
}

const ROLE_TEXT: Record<string, string> = {
  admin: '管理员',
  reviewer: '审核员',
  collector: '采集员'
}

// 管理台首页：管理员登录后的落地页，聚合全局进度、导入任务与录音审核
Page({
  data: {
    role: '',
    roleText: '',
    userId: '',
    isAdmin: false, // 仅 admin 可导入任务（reviewer 只有审核权限）
    loading: true,
    pkgs: [] as PkgItem[],
    overall: null as Progress | null,
    percent: 0,
    pool: 0,
    topCollectors: [] as CollectorRow[],
    allCollectors: [] as CollectorRow[],
    showAll: false
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
      const isAdmin = me.role === 'admin'
      this.setData({
        role: me.role,
        roleText: ROLE_TEXT[me.role] || me.role,
        userId: me.userId,
        isAdmin
      })

      // 全局采集进度（admin / reviewer 均可读），失败不阻塞首页
      try {
        const p = await request<any>({ url: '/admin/progress' })
        const rows: CollectorRow[] = (p.collectors || []).map((c: any) => ({
          ...c,
          percent: Math.round((c.completionRate || 0) * 100)
        }))
        this.setData({
          overall: p,
          percent: Math.round((p.completionRate || 0) * 100),
          pool: p.pool || 0,
          allCollectors: rows,
          topCollectors: rows.slice(0, 5)
        })
      } catch {}

      // 任务包列表仅 admin 可读；reviewer 请求会 403，这里直接跳过
      if (isAdmin) {
        try {
          const pkgRes = await request<{ list: PkgItem[] }>({ url: '/admin/packages' })
          this.setData({ pkgs: pkgRes.list || [] })
        } catch {}
      } else {
        this.setData({ pkgs: [] })
      }
    } catch (e: any) {
      wx.showToast({ title: e.message || '加载失败', icon: 'none' })
    } finally {
      this.setData({ loading: false })
      wx.stopPullDownRefresh()
    }
  },
  onToggleCollectors() {
    this.setData({ showAll: !this.data.showAll })
  },
  onImport() {
    wx.navigateTo({ url: '/subpackages/admin/import/import' })
  },
  onReview() {
    wx.navigateTo({ url: '/subpackages/admin/review/review' })
  },
  onAudit() {
    wx.navigateTo({ url: '/subpackages/admin/audit/audit' })
  },
  onProfile() {
    wx.navigateTo({ url: '/pages/profile/profile' })
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
