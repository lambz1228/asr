// 自定义 tabBar：管理员 / 采集员共用同一套底部导航
// 动效：活动项高亮块横向滑动（left 过渡）+ 图标弹跳 + 轻震动反馈
// 说明：组件自己从当前页面路由解析所处下标，页面无需手动同步 selected，
//      这样即使某个 tab 页被缓存复用，高亮状态也不会错位。
const LIST = [
  {
    pagePath: '/pages/home/home',
    text: '首页',
    icon: '/images/tabbar/home.png',
    activeIcon: '/images/tabbar/home-on.png'
  },
  {
    pagePath: '/pages/resources/resources',
    text: '学习资源',
    icon: '/images/tabbar/resources.png',
    activeIcon: '/images/tabbar/resources-on.png'
  },
  {
    pagePath: '/pages/record/record',
    text: '语言采集',
    icon: '/images/tabbar/record.png',
    activeIcon: '/images/tabbar/record-on.png'
  },
  {
    pagePath: '/pages/profile/profile',
    text: '我的',
    icon: '/images/tabbar/mine.png',
    activeIcon: '/images/tabbar/mine-on.png'
  }
]

// 每个 tab 占 1/4 宽，返回该项中心点的百分比位置（高亮块据此横向滑动）
function centerOf(index) {
  return index * 25 + 12.5
}

function gdata() {
  const app = getApp()
  if (app && !app.globalData) app.globalData = {}
  return app ? app.globalData : null
}

Component({
  data: {
    list: LIST,
    selected: 0,
    // 高亮块的 left（百分比）
    blob: centerOf(0)
  },

  attached() {
    const routed = this.routeIndex()
    const g = gdata()
    const prev = g && typeof g.tabIndex === 'number' ? g.tabIndex : routed
    // 先落到「上一次所在的 tab」，下一帧再滑到当前项 —— 切 tab 时有横滑动效
    this.setData({ selected: routed, blob: centerOf(prev) })
    if (prev !== routed) {
      setTimeout(() => this.setData({ blob: centerOf(routed) }), 32)
    }
    if (g) g.tabIndex = routed
  },

  pageLifetimes: {
    // 页面重新显示（含从其它 tab 切回本页）时重放滑动动效
    show() {
      const routed = this.routeIndex()
      const g = gdata()
      const prev = g && typeof g.tabIndex === 'number' ? g.tabIndex : routed
      if (prev !== routed) {
        this.setData({ blob: centerOf(prev) })
        setTimeout(() => this.settle(routed), 32)
      } else {
        this.settle(routed)
      }
    }
  },

  methods: {
    // 当前页面在 tab 列表中的下标
    routeIndex() {
      const pages = getCurrentPages()
      const cur = pages[pages.length - 1]
      const route = cur && cur.route ? '/' + cur.route : ''
      const i = LIST.findIndex((it) => it.pagePath === route)
      return i >= 0 ? i : 0
    },

    settle(index) {
      const g = gdata()
      if (g) g.tabIndex = index
      if (this.data.selected !== index || this.data.blob !== centerOf(index)) {
        this.setData({ selected: index, blob: centerOf(index) })
      }
    },

    onTap(e) {
      const i = Number(e.currentTarget.dataset.i)
      const item = LIST[i]
      if (!item) return
      wx.vibrateShort({ type: 'light', fail: () => {} })
      // 已在当前 tab：只给震动反馈，不重复跳转
      if (this.routeIndex() === i) {
        this.settle(i)
        return
      }
      // 立即推位（点击即有反馈）；globalData.tabIndex 仍保留「离开前所在的 tab」，
      // 由目标页 pageLifetimes.show 先瞬移回该位置再滑过来，形成横滑动效
      this.setData({ selected: i, blob: centerOf(i) })
      wx.switchTab({ url: item.pagePath })
    }
  }
})
