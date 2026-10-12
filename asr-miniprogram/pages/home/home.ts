import { request } from '../../utils/request'
import { getMe } from '../../utils/auth'
import { getConsentStatus } from '../../utils/consent'
import { goRecordTab, applyTitle, syncTabBar } from '../../utils/nav'
import {
  cachedFetch,
  invalidate,
  invalidateWorkData,
  hasCache,
  KEY,
  TTL_DATA
} from '../../utils/cache'

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
// 采集员排行默认只展示前 5
const TOP_COLLECTORS = 5
// 公共池预览条数
const POOL_PREVIEW = 3

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
//
// 性能约定（重要）：
//   1. 全量列表放在页面实例属性（allTasks / allPool / allCollectors）上，
//      **不进 data** —— data 里只放渲染需要的那几条，避免每次刷新把上千条任务
//      序列化进 setData 通道（那是切 tab 卡顿的主要来源）。
//   2. 取数统一走 cachedFetch：有缓存先渲染、后台静默刷新，只有真·首次
//      无缓存才铺骨架屏，所以来回切 tab 是「秒开 + 无感更新」。
//   3. 入场动画只在首次首屏播放一次（首次渲染后摘掉 .stagger），
//      否则每次数据回填都会重播 riseIn，观感是页面一直在抖。
Page({
  data: {
    // 仅「首次进入且无任何缓存」时才铺骨架，避免每次切回都闪一下
    skeleton: false,
    // 首次渲染时挂上一次性的入场动画类，随后摘掉
    anim: '',

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
    // 任务条数用标量表达，全量数组在实例属性 allTasks 上
    visibleTasks: [] as TaskItem[],
    totalTasks: 0,
    pendingCount: 0,
    restCount: 0,
    showAllTasks: false,
    poolPreview: [] as TaskItem[],
    poolTotal: 0,
    claiming: '',
    consentSigned: true,

    // ---- 管理员 / 审核员 ----
    overall: null as Progress | null,
    overallPercent: 0,
    poolCount: 0,
    visibleCollectors: [] as CollectorRow[],
    collectorCount: 0,
    showAllCollectors: false,
    pkgs: [] as PkgItem[],

    statusText: STATUS_TEXT
  },

  // ---- 非响应式数据（不参与 setData）----
  allTasks: [] as TaskItem[],
  allPool: [] as TaskItem[],
  allCollectors: [] as CollectorRow[],
  rendered: false,
  animTimer: null as any,

  onShow() {
    syncTabBar(this)
    this.load()
  },
  onPullDownRefresh() {
    // 下拉刷新 = 明确要最新数据：清缓存后重新走一遍（getMe 也会重新取）
    invalidate()
    this.load().finally(() => wx.stopPullDownRefresh())
  },
  onUnload() {
    if (this.animTimer) clearTimeout(this.animTimer)
  },

  // 统一取数：命中缓存立即渲染；旧值后台静默刷新后再回调刷新一次视图
  async fetchInto<T>(
    key: string,
    fetcher: () => Promise<T>,
    apply: (d: T) => void
  ): Promise<boolean> {
    try {
      const r = await cachedFetch<T>(key, TTL_DATA, fetcher, apply)
      apply(r.data)
      return true
    } catch {
      return false
    }
  },

  async load() {
    // 有角色缓存 → 整页可从缓存直出，不铺骨架
    const warm = hasCache(KEY.me)
    if (!this.rendered && !warm) this.setData({ skeleton: true })
    this.setData({ greeting: greeting() })
    try {
      const me = await getMe()
      const isManager = me.role === 'admin' || me.role === 'reviewer'
      // 同一页两个角色文案不同（首页 / 任务管理）：tabBar 的文字由组件按角色给，
      // 导航栏标题得自己跟着设，否则会出现「tab 写着任务管理、标题写着首页」
      applyTitle('home', isManager)
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
      this.markRendered()
    }
  },

  // 首屏就绪：关掉骨架屏，并开启一次性的入场动画
  markRendered() {
    if (this.rendered) {
      if (this.data.skeleton) this.setData({ skeleton: false })
      return
    }
    this.rendered = true
    this.setData({ skeleton: false, anim: 'stagger' })
    // 动画播完立即摘掉类名 —— 之后任何数据刷新都不会重播入场动画
    this.animTimer = setTimeout(() => this.setData({ anim: '' }), 1200)
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
    const ok = await this.fetchInto<Progress>(
      KEY.progress,
      () => request<Progress>({ url: '/progress' }),
      (p) => this.setData({ progress: p, percent: Math.round((p.completionRate || 0) * 100) })
    )
    if (!ok) this.setData({ progress: null, percent: 0 })
  },
  async loadTasks() {
    const ok = await this.fetchInto<{ list: TaskItem[] }>(
      KEY.tasks,
      () => request<{ list: TaskItem[] }>({ url: '/tasks' }),
      (d) => this.applyTasks(d.list || [])
    )
    if (!ok) this.applyTasks([])
  },
  // 全量入实例属性，data 只放要渲染的那几条
  applyTasks(list: TaskItem[]) {
    this.allTasks = list
    this.setData({
      totalTasks: list.length,
      pendingCount: list.filter((t) => ACTIVE_STATUS.indexOf(t.status) >= 0).length
    })
    this.applyTaskFilter()
  },
  applyTaskFilter() {
    const all = this.allTasks
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
    const ok = await this.fetchInto<{ list: TaskItem[] }>(
      KEY.pool,
      () => request<{ list: TaskItem[] }>({ url: '/tasks/pool' }),
      (d) => this.applyPool(d.list || [])
    )
    if (!ok) this.applyPool([])
  },
  applyPool(list: TaskItem[]) {
    this.allPool = list
    this.setData({ poolPreview: list.slice(0, POOL_PREVIEW), poolTotal: list.length })
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
      const res = await request<{ claimed: boolean }>({
        url: `/tasks/${id}/claim`,
        method: 'POST'
      })
      wx.showToast({
        title: res.claimed ? '已领取' : '该任务已被领取',
        icon: res.claimed ? 'success' : 'none'
      })
      // 写操作成功 → 任务 / 公共池 / 进度 三份缓存都过期了
      invalidateWorkData()
      invalidate(KEY.pool)
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
    await this.fetchInto<any>(
      KEY.adminProgress,
      () => request<any>({ url: '/admin/progress' }),
      (p) => this.applyOverall(p)
    )
    // 任务包列表仅 admin 可读；reviewer 请求会 403，直接跳过
    if (this.data.isAdmin) {
      await this.fetchInto<{ list: PkgItem[] }>(
        KEY.packages,
        () => request<{ list: PkgItem[] }>({ url: '/admin/packages' }),
        (d) => this.setData({ pkgs: d.list || [] })
      )
    } else {
      this.allCollectors = []
      this.setData({ pkgs: [], visibleCollectors: [], collectorCount: 0 })
    }
  },
  applyOverall(p: any) {
    const rows: CollectorRow[] = (p.collectors || []).map((c: any) => ({
      ...c,
      percent: Math.round((c.completionRate || 0) * 100)
    }))
    this.allCollectors = rows
    this.setData({
      overall: p,
      overallPercent: Math.round((p.completionRate || 0) * 100),
      poolCount: p.pool || 0,
      collectorCount: rows.length,
      visibleCollectors: rows.slice(0, TOP_COLLECTORS)
    })
  },
  onToggleCollectors() {
    const showAll = !this.data.showAllCollectors
    this.setData({
      showAllCollectors: showAll,
      visibleCollectors: showAll ? this.allCollectors : this.allCollectors.slice(0, TOP_COLLECTORS)
    })
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
