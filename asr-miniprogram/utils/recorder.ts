// 录音封装：基于微信 RecorderManager。
// 注意：微信原生仅支持 aac / mp3，WAV 必须由服务端转码（见方案第 3 节）。
const recorderManager = wx.getRecorderManager()

export interface RecordResult {
  tempFilePath: string
  duration: number
  /** 录音过程中是否被系统打断（来电 / 切换后其他应用占用麦克风 / 切后台） */
  interrupted: boolean
}

let stopResolver: ((r: RecordResult) => void) | null = null
let errorRejecter: ((e: any) => void) | null = null
// 中断标记：由 onInterruptionBegin（系统中断）或 stopAsInterrupted（切后台）置位
let interrupted = false

// 模块级只注册一次回调，避免重复 onStop 监听叠加
recorderManager.onStop((res) => {
  const result: RecordResult = {
    tempFilePath: res.tempFilePath,
    duration: res.duration,
    interrupted
  }
  interrupted = false
  if (stopResolver) {
    stopResolver(result)
    stopResolver = null
  }
})

recorderManager.onError((err) => {
  interrupted = false
  if (errorRejecter) {
    errorRejecter(err)
    errorRejecter = null
  }
})

// 系统中断（来电、语音通话、其他应用抢占麦克风）：微信会自动停止录音且不会自动恢复。
// 这里只置位；onStop 回调会把 interrupted 一起带回，页面据此提示重录（方案 §3）。
// 低版本基础库无此回调，用可选链兜底。
const rm = recorderManager as any
if (typeof rm.onInterruptionBegin === 'function') {
  rm.onInterruptionBegin(() => {
    interrupted = true
  })
}

export interface RecordOptions {
  sampleRate?: 8000 | 16000 | 44100
  numberOfChannels?: 1 | 2
  format?: 'aac' | 'mp3'
  encodeBitRate?: number
}

export function startRecord(opts: RecordOptions = {}): Promise<RecordResult> {
  return new Promise<RecordResult>((resolve, reject) => {
    interrupted = false
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

/** 正常停止：结果按当前中断标记返回 */
export function stopRecord() {
  recorderManager.stop()
}

/** 判定为中断后停止（切后台等）：先置标记再停，onStop 会带回 interrupted=true */
export function stopAsInterrupted() {
  interrupted = true
  recorderManager.stop()
}

/** 暂停录音：保留已录内容，可继续（RecorderManager.pause） */
export function pauseRecord() {
  recorderManager.pause()
}

/** 继续录音（RecorderManager.resume） */
export function resumeRecord() {
  recorderManager.resume()
}
