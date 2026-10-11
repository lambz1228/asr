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
      // 启动时自动重试此前未完成的音频上传（含上传中/失败态的本地记录）。
      // 延后 2.5s 再跑：首屏要发 /auth/me、/progress、/tasks、/tasks/pool 四个请求，
      // 补传（含文件上传）若同时挤进来会拖慢首屏，让用户感觉「一打开就卡」。
      setTimeout(() => retryPendingUploads(), 2500)
    }
  }
})
