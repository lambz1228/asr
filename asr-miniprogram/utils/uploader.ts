// 上传与断点恢复：录音完成后 saveFile 持久化，记录元数据，失败自动重试，uploadId 防重。
// 详见方案 5.1 上传恢复与本地存储策略。
export interface UploadMeta {
  taskId: string
  textId: string
  savedFilePath: string
  status: 'pending_upload' | 'uploaded' | 'upload_failed'
  retries: number
  uploadId: string
}

const META_KEY = 'pending_uploads'
const MAX_RETRIES = 3

function readMeta(): UploadMeta[] {
  return wx.getStorageSync(META_KEY) || []
}
function writeMeta(list: UploadMeta[]) {
  wx.setStorageSync(META_KEY, list)
}

// 简单哈希生成 uploadId（真实环境建议用更稳健的 hash + 服务端时间戳）
function genUploadId(taskId: string, version: number): string {
  const raw = `${taskId}-${version}-${Date.now()}`
  let h = 0
  for (let i = 0; i < raw.length; i++) h = (h * 31 + raw.charCodeAt(i)) >>> 0
  return h.toString(16)
}

export async function saveAndUpload(
  taskId: string,
  textId: string,
  tempFilePath: string,
  version: number
): Promise<void> {
  const savedFilePath = wx.getFileSystemManager().saveFileSync(tempFilePath)
  const uploadId = genUploadId(taskId, version)
  const meta: UploadMeta = {
    taskId,
    textId,
    savedFilePath,
    status: 'pending_upload',
    retries: 0,
    uploadId
  }
  const list = readMeta()
  list.push(meta)
  writeMeta(list)
  await doUpload(meta)
}

function doUpload(meta: UploadMeta): Promise<void> {
  const app = getApp<any>()
  const baseUrl = app.globalData.baseUrl
  const token = wx.getStorageSync('token')
  return new Promise<void>((resolve, reject) => {
    wx.uploadFile({
      url: baseUrl + `/tasks/${meta.taskId}/upload`,
      filePath: meta.savedFilePath,
      name: 'file',
      header: token ? { Authorization: 'Bearer ' + token } : {},
      formData: { textId: meta.textId, uploadId: meta.uploadId },
      success: (res: any) => {
        // wx.uploadFile 的 success 包含 4xx/5xx（如 409 未签同意书），需解析业务结果
        let body: any = {}
        try {
          body = JSON.parse(res.data)
        } catch {}
        if (res.statusCode === 200 && body && body.code === 0) {
          markStatus(meta.uploadId, 'uploaded')
          resolve()
          return
        }
        // 失败：根据后端状态处理
        const msg =
          (body && (body.message || body.detail)) ||
          ('HTTP ' + res.statusCode)
        const list = readMeta()
        const m = list.find((x) => x.uploadId === meta.uploadId)
        if (m) {
          m.retries += 1
          // 409（需同意书）直接标记失败，待用户补签后重新提交，避免无效重试
          m.status =
            res.statusCode === 409 || m.retries >= MAX_RETRIES
              ? 'upload_failed'
              : 'pending_upload'
          writeMeta(list)
        }
        const err: any = new Error(msg)
        err.statusCode = res.statusCode
        if (res.statusCode === 409) err.needConsent = true
        reject(err)
      },
      fail: () => {
        const list = readMeta()
        const m = list.find((x) => x.uploadId === meta.uploadId)
        if (m) {
          m.retries += 1
          m.status = m.retries >= MAX_RETRIES ? 'upload_failed' : 'pending_upload'
          writeMeta(list)
        }
        reject(new Error('upload failed'))
      }
    })
  })
}

function markStatus(uploadId: string, status: UploadMeta['status']) {
  const list = readMeta()
  const m = list.find((x) => x.uploadId === uploadId)
  if (m) {
    m.status = status
    writeMeta(list)
  }
}

// 下次进入小程序时，自动重试此前 pending 的上传
export function retryPendingUploads() {
  const list = readMeta().filter((m) => m.status === 'pending_upload')
  list.forEach((m) => doUpload(m).catch(() => {}))
}
