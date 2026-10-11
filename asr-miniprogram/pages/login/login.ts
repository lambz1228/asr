import { wxLogin, logout, routeAfterLogin } from '../../utils/auth'

Page({
  data: { loading: false },
  onLoad() {
    const token = wx.getStorageSync('token')
    if (token) this.route()
  },
  // 按角色分流：管理员 → 管理台；采集员 → 同意书 / 采集任务页
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
  // 本地演示用：以管理员身份登录，便于进入管理台（导入任务 / 审核）
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
