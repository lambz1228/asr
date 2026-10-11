import { request } from '../../utils/request'
import { getMe } from '../../utils/auth'
import { getConsentStatus } from '../../utils/consent'
import { goRecordTab } from '../../utils/nav'
import { openPrivacyContract } from '../../utils/privacy'
import { cachedFetch, invalidate, readCache, KEY, TTL_DATA } from '../../utils/cache'

interface TaskItem {
  id: string
  text: string
  status: string
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

// 导入模板示例（与「任务导入格式说明.md」保持一致：两列 —— 序号 + 汉语文本）
const TEMPLATE_SAMPLE = '序号,汉语文本\n1,今天天气很好，我们一起去公园散步。\n2,请把窗户关上，外面风有点大。'

// 录音规范要点
const RULES = [
  { icon: '🤫', title: '环境安静', desc: '关闭风扇 / 空调强风档，避免街噪与他人说话声' },
  { icon: '📏', title: '距离稳定', desc: '嘴距麦克风 10–15cm，全程保持一致，不要忽远忽近' },
  { icon: '🐢', title: '语速平稳', desc: '按自然语速朗读，约 200 字/分钟，句间稍作停顿' },
  { icon: '🚫', title: '不读错不回读', desc: '读错请停止并整句重录，不要中途纠正或重读某个字' },
  { icon: '🗣', title: '口语化自然', desc: '用普通话朗读，不加入方言、口头禅或拖长音' },
  { icon: '⏱', title: '单句时长', desc: '单条控制在 2–15 秒，太长可放慢但不要停顿过久' }
]

// 常见退回原因
const FAQ = [
  {
    q: '音频太轻 / 有明显底噪',
    a: '多因距离过远或环境嘈杂。请靠近麦克风 10–15cm，换到安静房间重录。'
  },
  {
    q: '读错字、漏字、自行加字',
    a: '必须与文本逐字一致。读错即刻停止，点「清除重录」整句重新录制。'
  },
  {
    q: '录音被打断（来电 / 切后台）',
    a: '微信录音在后台不可靠，被打断的内容可能不完整。请回到本页重新录制，避免切出小程序。'
  },
  {
    q: '上传后提示需要签署同意书',
    a: '语音属敏感个人信息，需先签署单独的《语音信息同意书》，签署后即可正常上传。'
  },
  {
    q: '任务被退回后怎么办',
    a: '在「首页 - 我的任务」中该条会标红并显示退回原因，点进去按原因重录即可，新录音会替换旧版本。'
  }
]

// 文本库一次最多渲染多少条：任务量可能上千，全量渲染会直接卡住页面
const TEXT_ROWS = 30

// 学习资源：两个身份共用的「规范 + 素材」页
//   采集员：录音规范、采集前自检、文本库检索（点按直进采集）、常见退回原因
//   管理员：录音规范 + 导入格式说明 / 导出说明 / 审核入口
//
// 性能约定：本页内容绝大部分是静态规范文案，真正依赖网络的只有角色与文本库。
// 全量文本放实例属性 allTexts，data 里只放渲染用的前 30 条，避免整表塞进 setData。
Page({
  data: {
    skeleton: false,
    anim: '',
    role: '',
    roleText: '',
    isManager: false,
    isCollector: false,
    consentSigned: true,
    rules: RULES,
    faq: FAQ,
    openFaq: -1,
    // 文本库（采集员）
    keyword: '',
    filtered: [] as TaskItem[],
    textCount: 0,
    shownCount: 0,
    statusText: STATUS_TEXT,
    templateSample: TEMPLATE_SAMPLE
  },

  allTexts: [] as TaskItem[],
  rendered: false,
  animTimer: null as any,

  onShow() {
    this.load()
  },
  onPullDownRefresh() {
    // 下拉 = 明确要最新数据
    invalidate()
    this.load().finally(() => wx.stopPullDownRefresh())
  },
  onUnload() {
    if (this.animTimer) clearTimeout(this.animTimer)
  },

  async load() {
    const warm = readCache(KEY.me) !== null
    if (!this.rendered && !warm) this.setData({ skeleton: true })
    try {
      const me = await getMe()
      const isManager = me.role === 'admin' || me.role === 'reviewer'
      this.setData({
        role: me.role,
        roleText: ROLE_TEXT[me.role] || me.role,
        isManager,
        isCollector: !isManager
      })
      if (isManager) {
        this.allTexts = []
        this.setData({ filtered: [], textCount: 0, shownCount: 0 })
        return
      }
      getConsentStatus()
        .then((st) => this.setData({ consentSigned: !!st.signed }))
        .catch(() => {})
      try {
        const r = await cachedFetch<{ list: TaskItem[] }>(
          KEY.tasks,
          TTL_DATA,
          () => request<{ list: TaskItem[] }>({ url: '/tasks' }),
          (fresh) => this.applyTexts(fresh.list || [])
        )
        this.applyTexts(r.data.list || [])
      } catch {
        this.applyTexts([])
      }
    } catch (e: any) {
      wx.showToast({ title: (e && e.message) || '加载失败', icon: 'none' })
    } finally {
      this.markRendered()
    }
  },

  // 首屏就绪：关骨架 + 一次性入场动画（之后刷新不再重播）
  markRendered() {
    if (this.rendered) {
      if (this.data.skeleton) this.setData({ skeleton: false })
      return
    }
    this.rendered = true
    this.setData({ skeleton: false, anim: 'stagger' })
    this.animTimer = setTimeout(() => this.setData({ anim: '' }), 1200)
  },

  applyTexts(list: TaskItem[]) {
    this.allTexts = list
    this.setData({ textCount: list.length })
    this.applyFilter()
  },
  onKeyword(e: any) {
    this.setData({ keyword: e.detail.value || '' })
    this.applyFilter()
  },
  clearKeyword() {
    this.setData({ keyword: '' })
    this.applyFilter()
  },
  applyFilter() {
    const kw: string = (this.data.keyword || '').trim()
    const list = this.allTexts
    const matched = kw ? list.filter((t) => t.text.indexOf(kw) >= 0) : list
    this.setData({ filtered: matched.slice(0, TEXT_ROWS), shownCount: matched.length })
  },
  onTapText(e: any) {
    goRecordTab(e.currentTarget.dataset.id)
  },

  onToggleFaq(e: any) {
    const i = Number(e.currentTarget.dataset.i)
    this.setData({ openFaq: this.data.openFaq === i ? -1 : i })
  },

  onGoConsent() {
    wx.navigateTo({ url: '/pages/consent/consent' })
  },
  onPrivacy() {
    openPrivacyContract()
  },
  onCopyTemplate() {
    wx.setClipboardData({
      data: TEMPLATE_SAMPLE,
      success: () => wx.showToast({ title: '模板示例已复制', icon: 'success' })
    })
  },
  onReview() {
    wx.navigateTo({ url: '/subpackages/admin/review/review' })
  }
})
