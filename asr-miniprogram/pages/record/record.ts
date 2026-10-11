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

Page({
  data: {
    taskId: '',
    text: '',
    recording: false,
    paused: false,
    recorded: false,
    interrupted: false,
    audioPath: '',
    playing: false,
    duration: 0,
    version: 1,
    statusText: '准备录音'
  },
  audioCtx: null as any,

  onLoad(options: any) {
    this.setData({
      taskId: options.taskId || '',
      text: decodeURIComponent(options.text || ''),
      // 已上传次数由服务端在 assignment.version 维护，这里仅用于生成唯一 uploadId
      version: Number(options.version || 0) + 1
    })
  },

  // 切后台 / 锁屏视为中断：微信录音在后台不可靠（方案 §3）
  onHide() {
    if (this.data.recording) {
      stopAsInterrupted()
      this.setData({ statusText: '已切到后台，录音中断' })
    }
  },
  onUnload() {
    if (this.data.recording) stopRecord()
    this.stopPlay()
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
      duration: 0,
      statusText: '录音中...'
    })
    try {
      const result: RecordResult = await startRecord({
        sampleRate: 16000,
        numberOfChannels: 1,
        format: 'aac'
      })
      const interrupted = !!result.interrupted
      this.setData({
        recorded: !!result.tempFilePath,
        audioPath: result.tempFilePath,
        recording: false,
        paused: false,
        interrupted,
        duration: result.duration,
        statusText: interrupted
          ? '录音被打断（来电 / 切后台），内容可能不完整，建议重录'
          : `录音完成（${(result.duration / 1000).toFixed(1)} 秒），可试听或提交`
      })
    } catch (e: any) {
      this.setData({ recording: false, paused: false, statusText: '录音失败，请检查麦克风权限' })
      const msg: string = (e && (e.errMsg || e.message)) || ''
      if (msg.indexOf('auth') >= 0 || msg.indexOf('permission') >= 0 || msg.indexOf('deny') >= 0) {
        // 麦克风权限被拒：引导去设置页开启
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
      this.setData({ paused: false, statusText: '录音中...' })
    } else {
      pauseRecord()
      this.setData({ paused: true, statusText: '已暂停，点「继续」接着录' })
    }
  },

  stopPlay() {
    if (this.audioCtx) {
      try {
        this.audioCtx.stop()
        this.audioCtx.destroy()
      } catch {}
      this.audioCtx = null
    }
    this.setData({ playing: false })
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
      duration: 0,
      statusText: '准备录音'
    })
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

    wx.showLoading({ title: '上传中' })
    try {
      await saveAndUpload(
        this.data.taskId,
        this.data.taskId,
        this.data.audioPath,
        this.data.version,
        this.data.interrupted
      )
      wx.showToast({ title: '上传成功', icon: 'success' })
      setTimeout(() => wx.navigateBack(), 800)
    } catch (e: any) {
      if (e && e.needConsent) {
        // 后端门禁：需先签署单独的语音信息同意书
        wx.hideLoading()
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
      wx.showToast({ title: '上传失败，已存入本地待重试', icon: 'none' })
    } finally {
      wx.hideLoading()
    }
  }
})
