import { request } from '../../utils/request'
import { getMe } from '../../utils/auth'
import { getConsentStatus } from '../../utils/consent'
import { goRecordTab } from '../../utils/nav'

interface TaskItem {
  id: string
  text: string
  status: string
  version: number
  rejectReason: string | null
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

interface PkgItem {
  pkgId: string
  name: string
  texts: number
  assignments: number
  pending: number
}

const STATUS_TEXT: Record<string, string> = {
  pending: '待领取',
  claimed: '待录制',
  uploading: '上传中',
  uploaded: '待审核',
  approved: '已通过',
  rejected: '已退回'
}

const ROLE_TEXT: Record<string, string> = {
  admin: '管理员',
  reviewer: '审核员',
  collector: '采集员'
}

// 待处理状态：首页默认只列这些，已通过的任务可展开查看
const ACTIVE_STATUS = ['pending', 'claimed', 'rejected', 'uploading']

// 首页最多渲染的任务条数（任务量可能上千，避免一次性渲染拖慢首屏）
const MAX_ROWS = 20

function greeting(): string {
  const h = new Date().getHours()
  if (h < 6) return '凌晨好'
  if (h < 12) return '上午好'
  if (h < 14) return '中午好'
  if (h < 19) return '下午好'
  return '晚上好'
}

// 统一首页：管理员 / 审核员与采集员共用同一个「首页」tab，内容按角色自适应
//   采集员：我的进度 + 我的任务 + 公共池（承接录音采集主流程）
//   管理员：全局采集进度 + 管理入口（导入 / 审核 / 审计）+ 采集员排行 + 任务包
Page({
  data: {
    loading: true,
    role: '',
    roleText: '',
    userId: '',
    initial: '',
    isAdmin: false,
    isManager: false,
    isCollector: false,
    greeting: '',

    // ---- 采集员 ----
    progress: null as Progress | null,
    percent: 0,
    tasks: [] as TaskItem[],
    visibleTasks: [] as TaskItem[],
    pendingCount: 0,
    restCount: 0,
    showAllTasks: false,
    pool: [] as TaskItem[],
    poolPreview: [] as TaskItem[],
    poolTotal: 0,
    claiming: '',
    consentSigned: true,

    // ---- 管理员 / 审核员 ----
    overall: null as Progress | null,
    overallPercent: 0,
    poolCount: 0,
    allCollectors: [] as CollectorRow[],
    topCollectors: [] as CollectorRow[],
    showAllCollectors: false,
    pkgs: [] as PkgItem[],

    statusText: STATUS_TEXT
  },

  onShow() {
    this.load()
  },
  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh())
  },

  async load() {
    this.setData({ loading: true, greeting: greeting() })
    try {
      const me = await getMe()
      const isManager = me.role === 'admin' || me.role === 'reviewer'
      this.setData({
        role: me.role,
        roleText: ROLE_TEXT[me.role] || me.role,
        userId: me.userId,
        initial: (me.userId || '?').slice(0, 1).toUpperCase(),
        isManager,
        isAdmin: me.role === 'admin',
        isCollector: !isManager
      })
      if (isManager) await this.loadManager()
      else await this.loadCollector()
    } catch (e: any) {
      const msg: string = (e && e.message) || '加载失败'
      wx.showToast({ title: msg, icon: 'none' })
      // 仅 token 失效才回登录页；后端未启动等网络问题留在本页
      if (/401|未登录|登录已过期|token/i.test(msg)) {
        setTimeout(() => wx.reLaunch({ url: '/pages/login/login' }), 800)
      }
    } finally {
      this.setData({ loading: false })
    }
  },

  // ---------- 采集员 ----------
  async loadCollector() {
    // 同意书状态仅作提醒，失败不阻塞首页
    getConsentStatus()
      .then((st) => this.setData({ consentSigned: !!st.signed }))
      .catch(() => {})
    await Promise.all([this.loadProgress(), this.loadTasks(), this.loadPool()])
  },
  async loadProgress() {
    try {
      const p = await request<Progress>({ url: '/progress' })
      this.setData({ progress: p, percent: Math.round((p.completionRate || 0) * 100) })
    } catch {
      this.setData({ progress: null, percent: 0 })
    }
  },
  async loadTasks() {
    try {
      const res = await request<{ list: TaskItem[] }>({ url: '/tasks' })
      const list = res.list || []
      this.setData({
        tasks: list,
        pendingCount: list.filter((t) => ACTIVE_STATUS.indexOf(t.status) >= 0).length
      })
      this.applyTaskFilter()
    } catch {
      this.setData({ tasks: [], visibleTasks: [], pendingCount: 0, restCount: 0 })
    }
  },
  applyTaskFilter() {
    const all = this.data.tasks
    const visible = this.data.showAllTasks ? all : all.filter((t) => t.status !== 'approved')
    this.setData({
      visibleTasks: visible.slice(0, MAX_ROWS),
      restCount: Math.max(0, visible.length - MAX_ROWS)
    })
  },
  onToggleTasks() {
    this.setData({ showAllTasks: !this.data.showAllTasks })
    this.applyTaskFilter()
  },
  async loadPool() {
    try {
      const res = await request<{ list: TaskItem[] }>({ url: '/tasks/pool' })
      const list = res.list || []
      this.setData({ pool: list, poolPreview: list.slice(0, 3), poolTotal: list.length })
    } catch {
      this.setData({ pool: [], poolPreview: [], poolTotal: 0 })
    }
  },
  onStartRecord() {
    goRecordTab()
  },
  onTapTask(e: any) {
    goRecordTab(e.currentTarget.dataset.id)
  },
  // 领取公共池任务：后端乐观锁，抢领失败返回 claimed=false
  async onClaim(e: any) {
    const id = e.currentTarget.dataset.id as string
    this.setData({ claiming: id })
    try {
      const res = await request<{ claimed: boolean }>({ url: `/tasks/${id}/claim`, method: 'POST' })
      wx.showToast({
        title: res.claimed ? '已领取' : '该任务已被领取',
        icon: res.claimed ? 'success' : 'none'
      })
      await Promise.all([this.loadTasks(), this.loadPool(), this.loadProgress()])
    } catch (err: any) {
      wx.showToast({ title: (err && err.message) || '领取失败', icon: 'none' })
    } finally {
      this.setData({ claiming: '' })
    }
  },
  onGoConsent() {
    wx.navigateTo({ url: '/pages/consent/consent' })
  },

  // ---------- 管理员 / 审核员 ----------
  async loadManager() {
    // 全局进度：admin / reviewer 均可读
    try {
      const p = await request<any>({ url: '/admin/progress' })
      const rows: CollectorRow[] = (p.collectors || []).map((c: any) => ({
        ...c,
        percent: Math.round((c.completionRate || 0) * 100)
      }))
      this.setData({
        overall: p,
        overallPercent: Math.round((p.completionRate || 0) * 100),
        poolCount: p.pool || 0,
        allCollectors: rows,
        topCollectors: rows.slice(0, 5)
      })
    } catch {}
    // 任务包列表仅 admin 可读；reviewer 请求会 403，直接跳过
    if (this.data.isAdmin) {
      try {
        const res = await request<{ list: PkgItem[] }>({ url: '/admin/packages' })
        this.setData({ pkgs: res.list || [] })
      } catch {}
    } else {
      this.setData({ pkgs: [] })
    }
  },
  onToggleCollectors() {
    this.setData({ showAllCollectors: !this.data.showAllCollectors })
  },
  onImport() {
    wx.navigateTo({ url: '/subpackages/admin/import/import' })
  },
  onReview() {
    wx.navigateTo({ url: '/subpackages/admin/review/review' })
  },
  onAudit() {
    wx.navigateTo({ url: '/subpackages/admin/audit/audit' })
  }
})
