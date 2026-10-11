import { wxLogin, logout, routeAfterLogin } from '../../utils/auth'

Page({
  data: { loading: false },
  onLoad() {
    const token = wx.getStorageSync('token')
    if (token) this.route()
  },
  // 按角色分流：两个身份都进入统一首页 tab，内容按角色自适应
  async route() {
    try {
      await routeAfterLogin()
    } catch {
      // 状态查询失败（如 token 失效）则清理并停留在登录页
      logout()
      wx.removeStorageSync('consentSigned')
    }
  },
  async onLogin() {
    await this.doLogin()
  },
  // 本地演示用：以管理员身份登录，直接查看管理视角的首页（导入 / 审核入口）
  async onLoginAsAdmin() {
    await this.doLogin('admin')
  },
  async doLogin(role?: 'admin' | 'collector') {
    this.setData({ loading: true })
    try {
      await wxLogin(role)
      await this.route()
    } catch (e: any) {
      wx.showToast({ title: '登录失败: ' + (e.message || ''), icon: 'none' })
    } finally {
      this.setData({ loading: false })
    }
  }
})
