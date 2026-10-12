import { request } from './request'
import { getConsentStatus } from './consent'
import { TAB } from './nav'
import { cachedFetch, invalidate, refreshFetch, KEY, TTL_ME } from './cache'

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
  // 换了账号（含演示身份切换）→ 上一个身份的缓存全部作废
  invalidate()
  return data
}

export function logout() {
  wx.removeStorageSync('token')
  // 退出后必须清缓存，否则换账号登录会读到上一个身份的数据
  invalidate()
  // 角色也一并清掉：不清的话，退出过程中若已经渲染出 tabBar，
  // 会按上一个身份的那套导航显示（采集员看到一个管理员的 2 项导航）
  rememberRole('')
}

export interface MeResult {
  userId: string
  role: string
}

// 把角色落到「同步可读」的地方，供自定义 tabBar 在**首帧**决定渲染几项导航。
// 为什么不能只用缓存层（utils/cache）：那层是纯内存的、冷启动时为空，
// 而 tabBar 的 attached 等不了 /auth/me 的异步返回。所以另存两处：
//   globalData.role  —— 本会话内同步可读
//   Storage 'role'   —— 跨启动兜底（app.ts onLaunch 会读回来）
// 角色变化后 tabBar 的 show 生命周期会复核并换列表，不需要页面主动通知。
export function rememberRole(role: string) {
  const app = getApp<any>()
  // 只在**真的变了**时才落盘：getMe 命中缓存时也会调进来，而 setStorageSync 是同步桥调用。
  // 一次切 tab 有 home / profile / record / resources 四个页面各调一次 getMe ——
  // 无条件写等于每次切换白做 4 次同步 IO（都在渲染关键路径上）。
  if (app && app.globalData && app.globalData.role === role) return
  if (app && app.globalData) app.globalData.role = role || ''
  if (role) wx.setStorageSync('role', role)
  else wx.removeStorageSync('role')
}

// 同步读当前角色（与 rememberRole 写入的两处同源，空串 = 还不知道）。
// 用途：需要在**渲染之前**就判断身份的地方 ——
//   1) 自定义 tabBar 首帧决定渲染几项；
//   2) 只服务采集员的页面（语言采集 / 学习资源）把管理员弹回「任务管理」：
//      页面栈可能被恢复（DevTools 保留页面栈、热重载、演示切换身份后回到旧页），
//      绝不能让管理员停在一个不属于他的页面上。
export function currentRole(): string {
  const app = getApp<any>()
  const fromApp = (app && app.globalData && app.globalData.role) || ''
  return fromApp || wx.getStorageSync('role') || ''
}

// 获取当前用户角色，用于决定是否展示审核台等管理入口。
// 走缓存：/auth/me 被首页、采集页、我的页、学习资源页各调一次，
// 有缓存后同一轮切换只会发一个请求，且返回是同步微任务，页面不再等网络。
export async function getMe(): Promise<MeResult> {
  const r = await cachedFetch<MeResult>(KEY.me, TTL_ME, () =>
    request<MeResult>({ url: '/auth/me', method: 'GET' })
  )
  rememberRole(r.data.role)
  return r.data
}

/** 下拉刷新用：强制绕过缓存重新取角色 */
export async function reloadMe(): Promise<MeResult> {
  const r = await refreshFetch<MeResult>(KEY.me, TTL_ME, () =>
    request<MeResult>({ url: '/auth/me', method: 'GET' })
  )
  rememberRole(r.role)
  return r
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
