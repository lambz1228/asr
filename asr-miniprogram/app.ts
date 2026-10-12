import { retryPendingUploads } from './utils/uploader'

interface IGlobalData {
  baseUrl: string
  token: string
  consentSigned: boolean
  /** 当前角色（admin / reviewer / collector）。
      自定义 tabBar 在 attached 当帧就要按角色决定渲染几项导航，等不了异步请求，
      所以角色必须有个**同步可读**的地方 —— 由 utils/auth.ts#getMe 写入，
      Storage（'role'）作跨启动兜底。空串表示还没拿到。 */
  role: string
}

App<IGlobalData>({
  globalData: {
    // 本地开发默认地址；正式环境改为 HTTPS 域名并在小程序后台配置合法域名
    baseUrl: 'http://localhost:8000/api',
    token: '',
    consentSigned: false,
    role: ''
  },
  onLaunch() {
    const token = wx.getStorageSync('token')
    // 先把上次登录记住的角色读进来：这样冷启动直接进 tab 页时，
    // tabBar 首帧就能拿到角色（getMe 是异步的，来不及）
    this.globalData.role = wx.getStorageSync('role') || ''
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
