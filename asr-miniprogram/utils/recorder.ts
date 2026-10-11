// 录音封装：基于微信 RecorderManager。
// 注意：微信原生仅支持 aac / mp3，WAV 必须由服务端转码（见方案第 3 节）。
const recorderManager = wx.getRecorderManager()

export interface RecordResult {
  tempFilePath: string
  duration: number
}

let stopResolver: ((r: RecordResult) => void) | null = null
let errorRejecter: ((e: any) => void) | null = null

// 模块级只注册一次回调，避免重复 onStop 监听叠加
recorderManager.onStop((res) => {
  if (stopResolver) {
    stopResolver({ tempFilePath: res.tempFilePath, duration: res.duration })
    stopResolver = null
  }
})
recorderManager.onError((err) => {
  if (errorRejecter) {
    errorRejecter(err)
    errorRejecter = null
  }
})

export interface RecordOptions {
  sampleRate?: 8000 | 16000 | 44100
  numberOfChannels?: 1 | 2
  format?: 'aac' | 'mp3'
  encodeBitRate?: number
}

export function startRecord(opts: RecordOptions = {}): Promise<RecordResult> {
  return new Promise<RecordResult>((resolve, reject) => {
    stopResolver = resolve
    errorRejecter = reject
    recorderManager.start({
      duration: 600000, // 最大 10 分钟
      sampleRate: opts.sampleRate || 16000,
      numberOfChannels: opts.numberOfChannels || 1,
      encodeBitRate: opts.encodeBitRate || 48000,
      format: opts.format || 'aac'
    })
  })
}

export function stopRecord() {
  recorderManager.stop()
}
