import { startRecord, stopRecord, RecordResult } from '../../utils/recorder'
import { saveAndUpload } from '../../utils/uploader'
import { ensurePrivacyAuthorize, openPrivacyContract } from '../../utils/privacy'

Page({
  data: {
    taskId: '',
    text: '',
    recording: false,
    recorded: false,
    audioPath: '',
    playing: false,
    version: 1,
    statusText: '准备录音'
  },
  onLoad(options: any) {
    this.setData({
      taskId: options.taskId || '',
      text: decodeURIComponent(options.text || '')
    })
  },
  async onStart() {
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
        content: '录音前需先同意微信《用户隐私保护指引》。可点击「查看协议」了解详情，同意后再点击开始录音。',
        confirmText: '查看协议',
        cancelText: '取消',
        success: (r) => {
          if (r.confirm) openPrivacyContract()
        }
      })
      return
    }

    this.setData({ recording: true, statusText: '录音中...' })
    try {
      const result: RecordResult = await startRecord({
        sampleRate: 16000,
        numberOfChannels: 1,
        format: 'aac'
      })
      this.setData({
        recorded: true,
        audioPath: result.tempFilePath,
        recording: false,
        statusText: '录音完成，可试听或重录'
      })
    } catch (e: any) {
      this.setData({ recording: false, statusText: '录音失败，请检查麦克风权限' })
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
  onPlay() {
    const ctx = wx.createInnerAudioContext()
    ctx.src = this.data.audioPath
    ctx.onPlay(() => this.setData({ playing: true }))
    ctx.onEnded(() => this.setData({ playing: false }))
    ctx.onError(() => {
      this.setData({ playing: false })
      wx.showToast({ title: '播放失败', icon: 'none' })
    })
    ctx.play()
  },
  onRerecord() {
    this.setData({ recorded: false, audioPath: '', statusText: '准备录音' })
  },
  async onSubmit() {
    if (!this.data.recorded) {
      wx.showToast({ title: '请先完成录音', icon: 'none' })
      return
    }
    wx.showLoading({ title: '上传中' })
    try {
      await saveAndUpload(this.data.taskId, this.data.taskId, this.data.audioPath, this.data.version)
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
