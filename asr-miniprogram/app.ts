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
    // 本地开发默认地址；正式环境改为 HTTPS 域名并在小程序后台配置合法域名。
    //
    // ⚠️ 这里必须写 127.0.0.1，**不能写 localhost**（实测，Windows 上踩过）：
    // 本机 `localhost` 先解析到 ::1（IPv6），而后端只监听 0.0.0.0（IPv4），
    // 于是 ::1 的连接要等 **2 秒**才被拒（IPv6 回环空端口静默丢包 + SYN 重传）。
    // `wx.request` 每次都新建连接、不 keep-alive，于是**每个请求白等 2 秒** ——
    // 页面 onShow 一发 4 个请求就整屏卡 2 秒，用户反馈「切换卡顿、延迟高」。
    // 改成 IP 字面量就没有解析过程，直接走 IPv4，实测新建连接 2~20ms。
    //
    // 反过来也别把后端改成 `uvicorn --host ::`：Windows 上绑定 [::] **不收 IPv4**，
    // 127.0.0.1 会被拒，真机局域网联调也会一起断。保持 0.0.0.0。
    // 真机调试请改成本机局域网 IP（如 http://192.168.1.10:8000/api），那是单一地址、无此问题。
    baseUrl: 'http://127.0.0.1:8000/api',
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
