// 统一导航入口。
//
// 底部导航**按角色分两套**（见 custom-tab-bar/index.js）：
//   采集员（collector）   首页 · 学习资源 · 语言采集 · 我的
//   管理员 / 审核员        任务管理 · 个人中心
// 页面本身是共用的，靠角色自适应内容。
//
// ⚠️ app.json 的 tabBar.list 必须保留全部 4 项 —— 只有声明过的页面才能 switchTab，
//    而采集员要切到 学习资源 / 语言采集。裁剪只发生在渲染层。
export const TAB = {
  home: '/pages/home/home',
  resources: '/pages/resources/resources',
  record: '/pages/record/record',
  profile: '/pages/profile/profile'
}

// 同一页面在两个角色下的文案。**tabBar 的文字在 custom-tab-bar/index.js 里**
// （组件得自带一份才能渲染），这里放导航栏标题；两处必须一致，
// 否则会出现「tab 写着任务管理、页面标题写着首页」这种自相矛盾的观感。
// 页面在 getMe 拿到角色后调 applyTitle() 设一次即可。
export const TITLE: Record<string, { manager: string; collector: string }> = {
  home: { manager: '任务管理', collector: '首页' },
  profile: { manager: '个人中心', collector: '我的' }
}

export function applyTitle(key: 'home' | 'profile', isManager: boolean) {
  const t = TITLE[key]
  if (!t) return
  wx.setNavigationBarTitle({ title: isManager ? t.manager : t.collector })
}

// tabBar 页面不支持 query 参数，跨 tab 传递「待录任务」改用本地存储中转
const PENDING_KEY = 'pendingTaskId'

export function setPendingTask(taskId: string) {
  wx.setStorageSync(PENDING_KEY, taskId)
}

// 取出并消费待录任务（只生效一次，避免下次进采集页仍跳回旧任务）
export function takePendingTask(): string {
  const id = wx.getStorageSync(PENDING_KEY) || ''
  if (id) wx.removeStorageSync(PENDING_KEY)
  return id
}

// 跳到「语言采集」tab；带 taskId 时该条任务会被直接定位
export function goRecordTab(taskId?: string) {
  if (taskId) setPendingTask(taskId)
  wx.switchTab({ url: TAB.record })
}

export function goHomeTab() {
  wx.switchTab({ url: TAB.home })
}
