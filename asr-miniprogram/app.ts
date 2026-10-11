import { retryPendingUploads } from './utils/uploader'

interface IGlobalData {
  baseUrl: string
  token: string
  consentSigned: boolean
}

App<IGlobalData>({
  globalData: {
    // 本地开发默认地址；正式环境改为 HTTPS 域名并在小程序后台配置合法域名
    baseUrl: 'http://localhost:8000/api',
    token: '',
    consentSigned: false
  },
  onLaunch() {
    const token = wx.getStorageSync('token')
    if (token) {
      this.globalData.token = token
      this.globalData.consentSigned = !!wx.getStorageSync('consentSigned')
      // 启动时自动重试此前未完成的音频上传（含上传中/失败态的本地记录）
      retryPendingUploads()
    }
  }
})
