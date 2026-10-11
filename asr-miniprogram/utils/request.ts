interface RequestOptions {
  url: string
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  data?: any
  auth?: boolean
}

// 统一请求封装：自动拼接 baseUrl、携带 JWT、解析 {code,message,data} 业务信封
export function request<T = any>(opts: RequestOptions): Promise<T> {
  const app = getApp<any>()
  const baseUrl = app.globalData.baseUrl
  const token = wx.getStorageSync('token')
  return new Promise<T>((resolve, reject) => {
    wx.request({
      url: baseUrl + opts.url,
      method: opts.method || 'GET',
      data: opts.data,
      header: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: 'Bearer ' + token } : {})
      },
      success: (res: any) => {
        const body = res.data
        if (res.statusCode === 200 && body && body.code === 0) {
          resolve(body.data as T)
          return
        }
        // 业务失败：优先展示后端 message，其次 HTTP 状态码
        reject(new Error((body && body.message) || ('HTTP ' + res.statusCode)))
      },
      fail: (err: any) => {
        // wx.request 失败（多为后端未启动 / 域名校验未通过 / 网络不通）
        const msg = (err && (err.errMsg || err.message)) || '网络请求失败'
        reject(new Error(msg + '（请确认后端已启动：start-server.bat）'))
      }
    })
  })
}
