// 自定义 tabBar：管理员 / 采集员共用同一套底部导航
// 说明：组件自己从当前页面路由解析所处下标，页面无需手动同步 selected，
//      这样即使某个 tab 页被缓存复用，高亮状态也不会错位。
//
// 【为什么不从「上一次所在的 tab」滑过来】
// 自定义 tabBar 是「每个页面各有一个实例」。切 tab 时微信会新建目标页的实例，
// 老实例随页面销毁，两块高亮块之间没有共享的 DOM，所以「从上一项滑过来」只能靠
// 新实例先把自己摆到旧位置、下一帧再滑到位来伪造。代价是导航比页面慢半拍：
//   点击(t=0) → 老实例滑向目标 → 切换完成、新页已可见
//   → 新实例首帧落在旧位置(错的) → 32ms 后开始滑 → 再 400ms 才到位
// 结果：页面早就切好了，高亮块还在路上（≈430ms），看起来就是「导航跟不上」。
// 正确做法是让新实例**首个渲染帧就落在正确位置**，并禁掉那一帧的过渡
// （否则页面被缓存复用、show 时纠正位置同样会滑一下）。
// 动效保留在不会滞后于页面的地方：点击瞬间老实例滑向目标（离场反馈），
// 以及新页图标/高亮块的 pop（入场反馈）。
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

Component({
  data: {
    list: LIST,
    // 高亮图标 / 文案所属项
    selected: 0,
    // 高亮块所在项
    blobIdx: 0,
    // 是否开启位置过渡。默认 false：位置变化「立刻」生效，不滑。
    // 只在点击时打开 —— 那是唯一需要过渡的地方（离场指向感）。
    // 不在别处「先关再异步打开」：setData 是否与下一次渲染合并不可控，
    // 一旦合并就会让纠正位置的那一帧带上过渡，又变成滑 400ms 的滞后。
    anim: false
  },

  attached() {
    // 首个渲染帧就落到正确位置（不播过渡）
    this.sync(false)
  },

  pageLifetimes: {
    // 页面重新显示（含从其它 tab 切回被缓存的页面）时，位置必须立即纠正
    show() {
      this.sync(false)
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

    // 把高亮同步到当前路由所在项。anim=false 表示瞬移（禁过渡）。
    sync(anim) {
      const i = this.routeIndex()
      if (this.data.selected === i && this.data.blobIdx === i && this.data.anim === anim) return
      this.setData({ selected: i, blobIdx: i, anim })
    },

    onTap(e) {
      const i = Number(e.currentTarget.dataset.i)
      const item = LIST[i]
      if (!item) return
      // 已在当前 tab：不重复跳转
      if (this.routeIndex() === i) {
        this.sync(true)
        return
      }
      // 离场反馈：点击瞬间让当前页的高亮块滑向目标（此时过渡是开着的）。
      // 老实例很快随页面销毁，所以这段滑动只作「指向感」，不承担到位职责 ——
      // 到位由目标页实例的首帧保证。
      this.setData({ selected: i, blobIdx: i, anim: true })
      wx.switchTab({
        url: item.pagePath,
        // 切换失败（如并发点击）：立刻回到真实位置，不留错误高亮
        fail: () => this.sync(false)
      })
    }
  }
})
