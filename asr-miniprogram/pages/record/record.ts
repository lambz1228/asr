import { request } from '../../utils/request'
import { getMe } from '../../utils/auth'
import {
  startRecord,
  stopRecord,
  stopAsInterrupted,
  pauseRecord,
  resumeRecord,
  RecordResult
} from '../../utils/recorder'
import { saveAndUpload } from '../../utils/uploader'
import { ensurePrivacyAuthorize, openPrivacyContract } from '../../utils/privacy'
import { takePendingTask, TAB } from '../../utils/nav'

// 队列中的一条任务（来自 GET /tasks）
interface QItem {
  id: string
  text: string
  textId: string
  pkgId: string
  pkgName: string
  status: string
  version: number
  rejectReason: string | null
}

// 与 recorder 的最大时长一致（10 分钟）
const MAX_SECONDS = 600

function fmtClock(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
}

Page({
  data: {
    loading: true,
    queue: [] as QItem[],
    index: 0,
    total: 0,
    current: null as QItem | null,
    // 队列为空（无任务可采）时展示空态
    empty: false,
    isManager: false,
    // 信息条
    speaker: '',
    // 录音状态
    recording: false,
    paused: false,
    recorded: false,
    interrupted: false,
    playing: false,
    audioPath: '',
    elapsed: 0,
    timerText: '00:00',
    recLabel: '点击录音',
    // 已录过则提示会替换旧录音（version > 0）
    replacing: false,
    version: 1,
    // 切任务时文本区的滑入方向类（成对交替，强制重放动画）
    slideCls: 's-r1',
    // 面板内瞬时提示（如「上传成功」）
    toast: '',
    statusText: ''
  },
  audioCtx: null as any,
  timer: null as any,
  appHideHandler: null as any,
  initialTaskId: '',
  fallbackText: '',
  fallbackVersion: 0,

  onLoad(options: any) {
    // tab 页进入时无参数；带参数的旧入口（列表页 navigateTo）仍兼容
    this.initialTaskId = options.taskId || ''
    this.fallbackText = decodeURIComponent(options.text || '')
    this.fallbackVersion = Number(options.version || 0)
    this.loadIdentity()
    // 仅「切到后台 / 锁屏」视为中断（微信录音在后台不可靠，方案 §3）；
    // 切换底部 tab 只隐藏页面、小程序仍在前台，录音可继续，故不按中断处理
    this.appHideHandler = () => {
      if (this.data.recording) {
        stopAsInterrupted()
        this.setData({ statusText: '已切到后台，录音中断' })
      }
    }
    wx.onAppHide(this.appHideHandler)
  },
  // 本页是 tab 页：每次回到本页都同步一次队列（录音中不打扰）
  onShow() {
    if (this.data.recording) return
    this.syncQueue()
  },
  onPullDownRefresh() {
    if (this.data.recording) {
      wx.stopPullDownRefresh()
      return
    }
    this.syncQueue().finally(() => wx.stopPullDownRefresh())
  },
  onUnload() {
    if (this.data.recording) stopRecord()
    this.clearTimer()
    this.stopPlay()
    if (this.appHideHandler) wx.offAppHide(this.appHideHandler)
  },

  async loadIdentity() {
    try {
      const me = await getMe()
      this.setData({
        speaker: me.userId || '',
        isManager: me.role === 'admin' || me.role === 'reviewer'
      })
    } catch {
      this.setData({ speaker: '' })
    }
  },

  // 同步「我的任务」队列，并定位到需要采集的那一条：
  //   优先取首页 / 学习资源页跨 tab 传入的待录任务，其次取本页首次进入时的参数
  async syncQueue() {
    const pending = takePendingTask()
    this.setData({ loading: true })
    try {
      const res = await request<{ list: QItem[] }>({ url: '/tasks' })
      const list = res.list || []
      if (!list.length) {
        this.setData({ loading: false })
        if (!this.data.queue.length) this.applyFallback()
        return
      }
      const current = this.data.current
      // 首次定位用的入口参数只生效一次，避免后续回到本页反复跳回旧任务
      const targetId = pending || this.initialTaskId || (current ? current.id : '')
      this.initialTaskId = ''
      this.setData({ queue: list, total: list.length, loading: false, empty: false })

      const idx = targetId ? list.findIndex((x) => x.id === targetId) : -1
      const curIdx = current ? list.findIndex((x) => x.id === current.id) : -1
      if (idx >= 0) {
        // 目标就是当前这条时只刷新数据，避免重置已录未提交的音频
        if (current && current.id === targetId) this.refreshCurrent(idx)
        else this.applyTask(idx)
      } else if (curIdx >= 0) {
        this.refreshCurrent(curIdx)
      } else {
        this.applyTask(0)
      }
    } catch (e: any) {
      this.setData({ loading: false, statusText: '任务加载失败，可下拉重试' })
      if (!this.data.queue.length) this.applyFallback()
    }
  },

  // 列表数据变化但保留当前选中项与录音状态（如任务被退回后重新拉取）
  refreshCurrent(i: number) {
    const item = this.data.queue[i]
    if (!item) return
    this.setData({
      index: i,
      current: item,
      replacing: (item.version || 0) > 0,
      statusText: item.rejectReason ? '该任务曾被退回，请按退回原因重录' : this.data.statusText
    })
  },

  // 兜底：/tasks 未含该任务（或加载失败）且由旧入口带参进入时，用参数构造单条队列
  applyFallback(list?: QItem[]) {
    if (list && list.length) {
      this.applyTask(0)
      return
    }
    if (!this.initialTaskId) {
      // 无任务可采（未分配 / 管理员身份）：展示空态，不构造假任务
      this.setData({ queue: [], total: 0, current: null, index: 0, empty: true })
      return
    }
    const single: QItem = {
      id: this.initialTaskId,
      text: this.fallbackText,
      textId: '',
      pkgId: '',
      pkgName: '',
      status: 'claimed',
      version: this.fallbackVersion,
      rejectReason: null
    }
    this.setData({ queue: [single], total: 1, empty: false })
    this.applyTask(0)
  },

  // 切换到第 i 条：重置录音区状态
  applyTask(i: number) {
    const item = this.data.queue[i]
    if (!item) return
    this.stopPlay()
    this.clearTimer()
    // 向后翻（下一条）从右侧滑入，向前翻（上一条）从左侧滑入；
    // 两个类名交替使用，保证连续同向切换时动画也会重放
    const dir = i < this.data.index ? 'l' : 'r'
    const next = this.data.slideCls === `s-${dir}1` ? `s-${dir}2` : `s-${dir}1`
    this.setData({
      index: i,
      current: item,
      slideCls: next,
      replacing: (item.version || 0) > 0,
      version: (item.version || 0) + 1,
      recording: false,
      paused: false,
      recorded: false,
      interrupted: false,
      audioPath: '',
      playing: false,
      elapsed: 0,
      timerText: '00:00',
      recLabel: '点击录音',
      toast: '',
      statusText: item.rejectReason
        ? '该任务曾被退回，请按退回原因重录'
        : ''
    })
  },

  // 切换任务前的守卫：录音中禁止切换；已录未提交需二次确认
  async guardSwitch(): Promise<boolean> {
    if (this.data.recording) {
      wx.showToast({ title: '请先停止当前录音', icon: 'none' })
      return false
    }
    if (this.data.recorded) {
      return await new Promise<boolean>((resolve) => {
        wx.showModal({
          title: '放弃当前录音？',
          content: '这段录音尚未提交，切换任务会丢失它。',
          confirmText: '放弃并切换',
          cancelText: '留在本页',
          success: (r) => resolve(!!r.confirm),
          fail: () => resolve(false)
        })
      })
    }
    return true
  },
  async onPrev() {
    if (this.data.index <= 0) return
    if (!(await this.guardSwitch())) return
    this.applyTask(this.data.index - 1)
  },
  async onNext() {
    if (this.data.index >= this.data.total - 1) return
    if (!(await this.guardSwitch())) return
    this.applyTask(this.data.index + 1)
  },

  // ---- 计时器 ----
  startTimer() {
    this.clearTimer()
    this.timer = setInterval(() => {
      if (this.data.recording && !this.data.paused) {
        const e = this.data.elapsed + 1
        this.setData({ elapsed: e, timerText: fmtClock(e) })
        if (e >= MAX_SECONDS) {
          wx.showToast({ title: '已达最长时长，自动停止', icon: 'none' })
          stopRecord()
        }
      }
    }, 1000)
  },
  clearTimer() {
    if (this.timer) {
      clearInterval(this.timer)
      this.timer = null
    }
  },

  async onToggleRecord() {
    // 录音中再次点击 = 停止录音（结果由 startRecord 的 Promise 在 onStop 时返回）
    if (this.data.recording) {
      stopRecord()
      return
    }

    // 合规：录音属隐私接口，开始前先过微信平台隐私授权
    const authorized = await ensurePrivacyAuthorize()
    if (!authorized) {
      wx.showModal({
        title: '需要隐私授权',
        content:
          '录音前需先同意微信《用户隐私保护指引》。可点击「查看协议」了解详情，同意后再点击开始录音。',
        confirmText: '查看协议',
        cancelText: '取消',
        success: (r) => {
          if (r.confirm) openPrivacyContract()
        }
      })
      return
    }

    this.setData({
      recording: true,
      paused: false,
      recorded: false,
      interrupted: false,
      audioPath: '',
      elapsed: 0,
      timerText: '00:00',
      recLabel: '点击停止',
      toast: '',
      statusText: '录音中，请朗读上方文本'
    })
    this.startTimer()
    try {
      const result: RecordResult = await startRecord({
        sampleRate: 16000,
        numberOfChannels: 1,
        format: 'aac'
      })
      this.clearTimer()
      const sec = Math.round((result.duration || 0) / 1000)
      const interrupted = !!result.interrupted
      this.setData({
        recorded: !!result.tempFilePath,
        audioPath: result.tempFilePath,
        recording: false,
        paused: false,
        interrupted,
        elapsed: sec,
        timerText: fmtClock(sec),
        recLabel: interrupted ? '已中断，建议重录' : '点击重录',
        statusText: interrupted
          ? '录音被打断（来电 / 切后台），内容可能不完整，建议清除重录'
          : `录音完成（${sec} 秒），可试听后保存提交`
      })
    } catch (e: any) {
      this.clearTimer()
      this.setData({
        recording: false,
        paused: false,
        recLabel: '点击录音',
        statusText: '录音失败，请检查麦克风权限'
      })
      const msg: string = (e && (e.errMsg || e.message)) || ''
      if (msg.indexOf('auth') >= 0 || msg.indexOf('permission') >= 0 || msg.indexOf('deny') >= 0) {
        wx.showModal({
          title: '需要麦克风权限',
          content: '请在「设置」中开启麦克风权限后重试。',
          confirmText: '去设置',
          success: (r) => {
            if (r.confirm) wx.openSetting({})
          }
        })
      } else {
        wx.showToast({ title: '录音失败，请重试', icon: 'none' })
      }
    }
  },

  // 暂停 / 继续：暂停期间已录内容保留
  onTogglePause() {
    if (!this.data.recording) return
    if (this.data.paused) {
      resumeRecord()
      this.setData({ paused: false, statusText: '录音中，请朗读上方文本' })
    } else {
      pauseRecord()
      this.setData({ paused: true, statusText: '已暂停，点「继续」接着录' })
    }
  },

  // ---- 试听 ----
  stopPlay() {
    if (this.audioCtx) {
      try {
        this.audioCtx.stop()
        this.audioCtx.destroy()
      } catch {}
      this.audioCtx = null
    }
    if (this.data.playing) this.setData({ playing: false })
  },
  onPlay() {
    if (this.data.playing) {
      this.stopPlay()
      return
    }
    const ctx = wx.createInnerAudioContext()
    ctx.src = this.data.audioPath
    ctx.onPlay(() => this.setData({ playing: true }))
    ctx.onEnded(() => this.setData({ playing: false }))
    ctx.onError(() => {
      this.setData({ playing: false })
      wx.showToast({ title: '播放失败', icon: 'none' })
    })
    ctx.play()
    this.audioCtx = ctx
  },

  onRerecord() {
    this.stopPlay()
    this.setData({
      recorded: false,
      audioPath: '',
      interrupted: false,
      elapsed: 0,
      timerText: '00:00',
      recLabel: '点击录音',
      statusText: ''
    })
  },

  flashToast(text: string) {
    this.setData({ toast: text })
    setTimeout(() => this.setData({ toast: '' }), 1600)
  },

  // 提交成功后：还有下一条就自动切过去（连续采集）；否则提示本队列已完成
  // 本页是 tab 页，不能 navigateBack，改为留在本页并引导回首页看进度
  advanceOrBack() {
    const i = this.data.index
    if (i + 1 < this.data.queue.length) {
      this.applyTask(i + 1)
      return
    }
    this.setData({
      recording: false,
      statusText: '本队列已全部提交，可在「首页」查看进度与审核结果'
    })
    wx.showToast({ title: '本队列已完成', icon: 'none' })
  },

  onGoHome() {
    wx.switchTab({ url: TAB.home })
  },

  async onSubmit() {
    if (!this.data.recorded) {
      wx.showToast({ title: '请先完成录音', icon: 'none' })
      return
    }
    // 被打断的录音可能不完整，提交前二次确认，避免不合格音频进入审核（方案 §3）
    if (this.data.interrupted) {
      const proceed = await new Promise<boolean>((resolve) => {
        wx.showModal({
          title: '录音曾被打断',
          content: '这段录音在录制过程中被来电或切后台打断，内容可能不完整，建议重录后再提交。',
          confirmText: '仍然提交',
          cancelText: '重新录制',
          success: (r) => resolve(!!r.confirm),
          fail: () => resolve(false)
        })
      })
      if (!proceed) {
        this.onRerecord()
        return
      }
    }

    const cur = this.data.current as QItem
    wx.showLoading({ title: '上传中' })
    try {
      await saveAndUpload(
        cur.id,
        cur.textId || cur.id,
        this.data.audioPath,
        this.data.version,
        this.data.interrupted
      )
      wx.hideLoading()
      // 本地队列状态同步，避免自动跳到下一条后再切回来仍是旧的
      const q = this.data.queue.slice()
      if (q[this.data.index]) {
        q[this.data.index] = { ...q[this.data.index], status: 'uploaded', version: this.data.version }
      }
      this.setData({ queue: q, recLabel: '已提交', statusText: '上传成功' })
      this.flashToast('上传成功')
      wx.showToast({ title: '上传成功', icon: 'success' })
      setTimeout(() => this.advanceOrBack(), 900)
    } catch (e: any) {
      wx.hideLoading()
      if (e && e.needConsent) {
        // 后端门禁：需先签署单独的语音信息同意书
        wx.showModal({
          title: '需签署同意书',
          content: '上传前需先签署单独的《语音信息同意书》。是否前往签署？',
          confirmText: '去签署',
          success: (r) => {
            if (r.confirm) wx.navigateTo({ url: '/pages/consent/consent' })
          }
        })
        return
      }
      this.setData({ statusText: '上传失败，已存入本地待重试' })
      wx.showToast({ title: '上传失败，已存入本地待重试', icon: 'none' })
    }
  }
})
