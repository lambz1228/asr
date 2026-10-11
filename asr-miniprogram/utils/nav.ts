// 统一导航入口：应用对「管理员 / 审核员」与「采集员」使用同一套底部导航
// （首页 / 学习资源 / 语言采集 / 我的），页面内容按角色自适应。
export const TAB = {
  home: '/pages/home/home',
  resources: '/pages/resources/resources',
  record: '/pages/record/record',
  profile: '/pages/profile/profile'
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
