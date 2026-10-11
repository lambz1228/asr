import { request } from './request'
import { getConsentStatus } from './consent'
import { TAB } from './nav'

// 管理侧角色（可进入管理台：导入任务 / 审核 / 导出）
export function isManagerRole(role: string): boolean {
  return role === 'admin' || role === 'reviewer'
}

export interface LoginResult {
  token: string
  userId: string
}

// 微信登录：用 wx.login 拿 code，交给后端换取 JWT
// role 仅本地开发态（DEV_MOCK_LOGIN）会生效，用于切换演示账号；生产后端会忽略它。
export async function wxLogin(role?: 'admin' | 'collector'): Promise<LoginResult> {
  const { code } = await wx.login()
  const data = await request<LoginResult>({
    url: '/auth/wx-login',
    method: 'POST',
    data: role ? { code, role } : { code }
  })
  wx.setStorageSync('token', data.token)
  return data
}

export function logout() {
  wx.removeStorageSync('token')
}

export interface MeResult {
  userId: string
  role: string
}

// 获取当前用户角色，用于决定是否展示审核台等管理入口
export async function getMe(): Promise<MeResult> {
  return request<MeResult>({ url: '/auth/me', method: 'GET' })
}

export type LoginRoute = 'manager' | 'collector'

// 登录后分流：两个身份进入同一套底部导航（首页 / 学习资源 / 语言采集 / 我的），
// 首页内容按角色自适应，因此这里不再分成两套入口页。
//   admin / reviewer → 首页（管理视角，不强制签语音同意书）
//   collector 等采集角色 → 未签同意书先进同意书页，已签进首页（采集视角）
// 返回实际分流去向，调用方可据此提示。
export async function routeAfterLogin(): Promise<LoginRoute> {
  const me = await getMe()
  if (isManagerRole(me.role)) {
    wx.switchTab({ url: TAB.home })
    return 'manager'
  }
  // 非管理角色一律按采集员处理；语音属敏感个人信息，采集前须单独同意
  const st = await getConsentStatus()
  if (st.signed) wx.switchTab({ url: TAB.home })
  else wx.reLaunch({ url: '/pages/consent/consent' })
  return 'collector'
}
