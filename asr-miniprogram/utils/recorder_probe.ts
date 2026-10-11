/**
 * recorder_probe.ts —— 真机录音参数探针
 *
 * 用途：在真机上录一小段，拿到「微信实际写出的文件」的客观参数，
 * 回填到《真机录音参数验证清单.md》的矩阵里。微信小程序端无法直接 ffprobe，
 * 本工具通过文件系统 API 取真实字节大小，并对文件头做格式嗅探，
 * 再结合录音时长估算码率，足以在采集端判断「格式 / 采样率 / 声道 / 时长上限 / 中断」是否达标。
 *
 * 注意：真实采样率 / 声道数需最终用 ffprobe 校验（见文档「本地复核」一节）。
 * 若后端处于 dev 态，可用 submitProbeReport() 直接上报，由服务端 ffprobe 复核并聚合。
 */

export interface RecordProbe {
  /** 文件字节数 */
  sizeBytes: number
  /** 录音时长（秒），优先用 onStop 返回的 duration，否则用前后台时间戳差 */
  durationSec: number
  /** 估算法：sizeBytes*8 / durationSec / 1000，单位 kbps */
  estimatedBitrateKbps: number
  /** 文件头嗅探结果：aac | mp3 | unknown */
  headerGuess: 'aac' | 'mp3' | 'unknown'
  /** 文件保存路径（可经 DevTools「文件系统」导出后做本地 ffprobe） */
  tempFilePath: string
}

/** 一档「请求参数组合」，用于遍历探测设备真实能力 */
export interface ProbeMatrixItem {
  label: string
  format: 'aac' | 'mp3'
  sampleRate: 8000 | 16000 | 44100 | 48000
  numberOfChannels: 1 | 2
}

/** 推荐的参数矩阵：覆盖 格式 / 采样率 / 声道 的关键组合（清单 V1–V6） */
export const PROBE_MATRIX: ProbeMatrixItem[] = [
  { label: 'V1/V2 基准', format: 'aac', sampleRate: 16000, numberOfChannels: 1 },
  { label: 'V3 高采样率', format: 'aac', sampleRate: 44100, numberOfChannels: 1 },
  { label: 'V4 48kHz 探测', format: 'aac', sampleRate: 48000, numberOfChannels: 1 },
  { label: 'V5/V6 双声道', format: 'aac', sampleRate: 16000, numberOfChannels: 2 },
  { label: 'MP3 备用格式', format: 'mp3', sampleRate: 16000, numberOfChannels: 1 },
]

const fs = wx.getFileSystemManager()

function sniffHeader(buf: ArrayBuffer): 'aac' | 'mp3' | 'unknown' {
  const bytes = new Uint8Array(buf)
  if (bytes.length < 2) return 'unknown'
  // AAC ADTS 同步字 0xFFF（12 位），即前两字节高 12 位为 1
  if (bytes[0] === 0xff && (bytes[1] & 0xf0) === 0xf0) return 'aac'
  // MP3 帧同步 0xFFEx，或 ID3 标签头
  if ((bytes[0] === 0xff && (bytes[1] & 0xe0) === 0xe0) || (bytes[0] === 0x49 && bytes[1] === 0x44 && bytes[2] === 0x33)) {
    return 'mp3'
  }
  return 'unknown'
}

function readHeader(tempFilePath: string, length = 4): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    fs.readFile({
      filePath: tempFilePath,
      position: 0,
      length,
      success: (res: WechatMiniprogram.ReadFileSuccessCallbackResult) => resolve(res.data as ArrayBuffer),
      fail: reject,
    } as any)
  })
}

/**
 * 探测一段录音的真实参数。
 * @param tempFilePath RecorderManager.onStop 返回的 res.tempFilePath
 * @param durationSec  onStop 返回的 res.duration（秒）；未提供则用 startTs/stopTs 估算
 * @param startTs      录音开始的 performance.now()/Date.now()（兜底用）
 * @param stopTs       录音结束的时间戳（兜底用）
 */
export async function probeRecording(
  tempFilePath: string,
  durationSec?: number,
  startTs?: number,
  stopTs?: number,
): Promise<RecordProbe> {
  // 1) 真实文件大小
  const info = await new Promise<WechatMiniprogram.GetFileInfoSuccessCallbackResult>((resolve, reject) => {
    fs.getFileInfo({ filePath: tempFilePath, success: resolve, fail: reject })
  })
  const sizeBytes = info.size

  // 2) 时长
  let dur = durationSec
  if (!dur && startTs && stopTs) {
    dur = (stopTs - startTs) / 1000
  }
  dur = dur && dur > 0 ? dur : 0

  // 3) 码率估算
  const estimatedBitrateKbps = dur > 0 ? (sizeBytes * 8) / dur / 1000 : 0

  // 4) 文件头嗅探
  let headerGuess: RecordProbe['headerGuess'] = 'unknown'
  try {
    const head = await readHeader(tempFilePath)
    headerGuess = sniffHeader(head)
  } catch {
    headerGuess = 'unknown'
  }

  return { sizeBytes, durationSec: dur, estimatedBitrateKbps, headerGuess, tempFilePath }
}

/**
 * 把探测结果汇总成一行「可粘贴进验证矩阵」的文本。
 */
export function formatProbeLine(p: RecordProbe, meta: { device: string; wechatVer: string; sampleRate: number; channels: number }): string {
  const kb = (p.sizeBytes / 1024).toFixed(1)
  const br = p.estimatedBitrateKbps.toFixed(1)
  return [
    meta.device,
    meta.wechatVer,
    `req=${meta.sampleRate}Hz/${meta.channels}ch`,
    `out=${p.headerGuess}`,
    `size=${kb}KB`,
    `dur=${p.durationSec.toFixed(1)}s`,
    `br≈${br}kbps`,
  ].join(' | ')
}

/** 上报单项探测结果的载荷 */
export interface ProbeReport {
  device: string
  wechatVer: string
  reqFormat: string
  reqSampleRate: number
  reqChannels: number
  sizeBytes: number
  durationSec: number
  estimatedBitrateKbps: number
  headerGuess: string
}

/**
 * 把一项探测结果上报到后端 dev 接口（`POST /api/dev/audio-probe`）。
 * 后端可能用 ffprobe 复核；主机侧带跑脚本再聚合出验证矩阵。
 * 仅在 ENV=dev 的后端可用。
 */
export function submitProbeReport(baseUrl: string, token: string, item: ProbeReport): Promise<void> {
  return new Promise((resolve, reject) => {
    const body = [
      'device=' + encodeURIComponent(item.device),
      'wechatVer=' + encodeURIComponent(item.wechatVer),
      'reqFormat=' + encodeURIComponent(item.reqFormat),
      'reqSampleRate=' + item.reqSampleRate,
      'reqChannels=' + item.reqChannels,
      'sizeBytes=' + item.sizeBytes,
      'duration=' + item.durationSec,
      'estBitrateKbps=' + item.estimatedBitrateKbps,
      'headerGuess=' + encodeURIComponent(item.headerGuess),
    ].join('&')
    wx.request({
      url: baseUrl + '/dev/audio-probe',
      method: 'POST',
      header: {
        'content-type': 'application/x-www-form-urlencoded',
        Authorization: 'Bearer ' + token,
      },
      data: body,
      success: (res: any) => {
        if (res.statusCode >= 200 && res.statusCode < 300) resolve()
        else reject(new Error('HTTP ' + res.statusCode))
      },
      fail: (e: any) => reject(e),
    })
  })
}

/** 探测 + 上报一步到位（不附带音频文件；如需 ffprobe 权威复核，改为走带文件的上传流程）。 */
export async function probeAndReport(
  baseUrl: string,
  token: string,
  tempFilePath: string,
  meta: { device: string; wechatVer: string; format: string; sampleRate: number; channels: number },
  durationSec?: number,
): Promise<RecordProbe> {
  const probe = await probeRecording(tempFilePath, durationSec)
  await submitProbeReport(baseUrl, token, {
    device: meta.device,
    wechatVer: meta.wechatVer,
    reqFormat: meta.format,
    reqSampleRate: meta.sampleRate,
    reqChannels: meta.channels,
    sizeBytes: probe.sizeBytes,
    durationSec: probe.durationSec,
    estimatedBitrateKbps: probe.estimatedBitrateKbps,
    headerGuess: probe.headerGuess,
  })
  return probe
}
