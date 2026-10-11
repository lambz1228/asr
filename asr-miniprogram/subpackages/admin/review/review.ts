import { request } from '../../../utils/request'

interface AudioItem {
  recordingId: string
  assignmentId: string
  version: number
  status: string
  realSampleRate: number | null
  realChannels: number | null
  realCodec: string | null
  duration: number | null
  qualityFlags: string[]
  transcode: string
  previewUrl: string
}

const STATUS_TEXT: Record<string, string> = {
  uploaded: '待审核',
  approved: '已通过',
  rejected: '已退回'
}

// 质量标记中文说明（方案 §5.2 + 端侧中断标记）
const FLAG_TEXT: Record<string, string> = {
  low_volume: '音量过低',
  clipping: '削波失真',
  too_much_silence: '静音过多',
  recording_interrupted: '录音曾中断'
}

Page({
  data: {
    filter: 'uploaded',
    items: [] as AudioItem[],
    displayItems: [] as AudioItem[],
    loading: true,
    playingId: '' as string,
    statusText: STATUS_TEXT,
    flagText: FLAG_TEXT
  },
  audioCtx: null as any,

  onShow() {
    this.load()
  },
  onHide() {
    this.stopPlay()
  },
  onUnload() {
    this.stopPlay()
  },
  onPullDownRefresh() {
    this.load()
  },

  async load() {
    this.setData({ loading: true })
    try {
      const res = await request<{ list: AudioItem[] }>({ url: '/admin/audios' })
      this.setData({ items: res.list || [] })
      this.applyFilter()
    } catch (e: any) {
      wx.showToast({ title: e.message || '加载失败', icon: 'none' })
    } finally {
      this.setData({ loading: false })
      wx.stopPullDownRefresh()
    }
  },

  setFilter(e: any) {
    this.setData({ filter: e.currentTarget.dataset.f })
    this.applyFilter()
  },
  applyFilter() {
    const f = this.data.filter
    const list = f === 'all' ? this.data.items : this.data.items.filter((i) => i.status === f)
    this.setData({ displayItems: list })
  },

  buildUrl(item: AudioItem): string {
    const app = getApp<any>()
    const base = (app.globalData.baseUrl || '').replace(/\/api$/, '')
    let u = item.previewUrl || ''
    if (!u) return ''
    if (u.startsWith('http')) return u
    const token = wx.getStorageSync('token') || ''
    const sep = u.indexOf('?') >= 0 ? '&' : '?'
    return base + u + sep + 'token=' + token
  },

  onPlay(e: any) {
    const id = e.currentTarget.dataset.id as string
    if (this.data.playingId === id) {
      this.stopPlay()
      return
    }
    const item = this.data.items.find((i) => i.recordingId === id)
    if (!item) return
    this.stopPlay()
    const url = this.buildUrl(item)
    if (!url) {
      wx.showToast({ title: '无可用音频', icon: 'none' })
      return
    }
    const ctx = wx.createInnerAudioContext()
    ctx.src = url
    ctx.onPlay(() => this.setData({ playingId: id }))
    ctx.onEnded(() => this.setData({ playingId: '' }))
    ctx.onError(() => {
      this.setData({ playingId: '' })
      wx.showToast({ title: '播放失败', icon: 'none' })
    })
    ctx.play()
    this.audioCtx = ctx
    this.setData({ playingId: id })
  },
  stopPlay() {
    if (this.audioCtx) {
      try {
        this.audioCtx.stop()
        this.audioCtx.destroy()
      } catch {}
      this.audioCtx = null
    }
    this.setData({ playingId: '' })
  },

  async onApprove(e: any) {
    const id = e.currentTarget.dataset.id as string
    wx.showLoading({ title: '提交中' })
    try {
      await request({ url: `/admin/audios/${id}/review`, method: 'POST', data: { action: 'approve' } })
      this.markReviewed(id, 'approved')
      wx.showToast({ title: '已通过', icon: 'success' })
    } catch (e: any) {
      wx.showToast({ title: e.message || '操作失败', icon: 'none' })
    } finally {
      wx.hideLoading()
    }
  },

  onReject(e: any) {
    const id = e.currentTarget.dataset.id as string
    wx.showModal({
      title: '退回录音',
      editable: true,
      placeholderText: '请填写退回原因（可选）',
      success: async (r) => {
        if (!r.confirm) return
        wx.showLoading({ title: '提交中' })
        try {
          await request({
            url: `/admin/audios/${id}/review`,
            method: 'POST',
            data: { action: 'reject', reason: r.content || '' }
          })
          this.markReviewed(id, 'rejected')
          wx.showToast({ title: '已退回', icon: 'none' })
        } catch (e: any) {
          wx.showToast({ title: e.message || '操作失败', icon: 'none' })
        } finally {
          wx.hideLoading()
        }
      }
    })
  },
  markReviewed(id: string, status: string) {
    const items = this.data.items.map((i) => (i.recordingId === id ? { ...i, status } : i))
    this.setData({ items })
    this.applyFilter()
  },

  async onExport() {
    wx.showLoading({ title: '导出中' })
    try {
      const res: any = await request({ url: '/admin/export', method: 'POST' })
      if (res.async) {
        wx.showToast({ title: '已创建导出任务', icon: 'none' })
        this.pollExport(res.pollUrl)
      } else {
        wx.showToast({ title: '导出完成（请在服务端获取）', icon: 'none' })
      }
    } catch (e: any) {
      wx.showToast({ title: e.message || '导出失败', icon: 'none' })
    } finally {
      wx.hideLoading()
    }
  },
  async pollExport(pollUrl: string) {
    const path = pollUrl.replace(/^\/api/, '')
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 2000))
      try {
        const st: any = await request({ url: path, method: 'GET' })
        if (st.status === 'done') {
          const url = st.url
          wx.showModal({
            title: '导出完成',
            content: '下载链接已生成，可复制到浏览器下载：\n' + url,
            confirmText: '复制链接',
            success: (r) => {
              if (r.confirm) wx.setClipboardData({ data: url })
            }
          })
          return
        }
        if (st.status === 'failed') {
          wx.showToast({ title: '导出失败', icon: 'none' })
          return
        }
      } catch {}
    }
    wx.showToast({ title: '导出超时，请稍后重试', icon: 'none' })
  }
})
