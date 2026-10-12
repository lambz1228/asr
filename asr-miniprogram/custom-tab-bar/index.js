// 自定义 tabBar：底部导航**按角色分两套**，采集员与管理员看到的项数不同。
//
//   采集员（collector）    首页 · 学习资源 · 语言采集 · 我的
//   管理员 / 审核员         任务管理 · 个人中心
//
// 为什么分：管理员不录音（采集页对他们是空态「当前身份无需采集」），也不需要学习资源，
// 管理动作（导入 / 审核 / 审计）全在首页里 —— 那两个 tab 对管理员只是噪声。
//
// ⚠️ 关键约束：app.json 的 tabBar.list 必须**保留全部 4 项**。
// 只有声明在 tabBar.list 里的页面才能被 switchTab 打开，而采集员要切到
// 「学习资源 / 语言采集」。所以列表裁剪只发生在渲染层：
// app.json 仍是全量声明，组件按角色决定渲染几项。
// 改这里时**不要**顺手去删 app.json 里的项，否则采集员那两个 tab 会切不过去。
//
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
//
// 文案与 utils/nav.ts 的 TITLE 是一对：这里给 tabBar 文字，那边给导航栏标题。
// 同一个页面对两个角色文案不同（首页 / 任务管理），改文案要**同时**改两处。
const LIST_COLLECTOR = [
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

const LIST_MANAGER = [
  {
    pagePath: '/pages/home/home',
    text: '任务管理',
    icon: '/images/tabbar/home.png',
    activeIcon: '/images/tabbar/home-on.png'
  },
  {
    pagePath: '/pages/profile/profile',
    text: '个人中心',
    icon: '/images/tabbar/mine.png',
    activeIcon: '/images/tabbar/mine-on.png'
  }
]

// 角色必须**同步**读到：组件在 attached 当帧就要决定渲染几项，等不了异步请求。
// 来源是 utils/auth.ts#getMe 写下的 globalData.role（Storage 作跨启动兜底）——
// 真机上任何一个 tab 页出现之前都必然先过登录分流，那时已经写过。
// 两边都拿不到（首次安装、token 失效等）就按采集员那套渲染：普通用户是默认身份，
// 而且那是最全的一套，不会把功能藏起来。
function resolveList() {
  const app = getApp()
  const role = (app && app.globalData && app.globalData.role) || wx.getStorageSync('role') || ''
  return role === 'admin' || role === 'reviewer' ? LIST_MANAGER : LIST_COLLECTOR
}

Component({
  data: {
    list: LIST_COLLECTOR,
    // 'collector' | 'manager'，仅用于判重（角色没变就不重复 setData）
    role: '',
    // 高亮块轨道宽 = 100 / 项数（%）。项数按角色变（4 或 2），
    // 所以宽度不能写死在 wxss 里，必须随列表一起下发，否则高亮块会落偏。
    trackW: 100 / LIST_COLLECTOR.length,
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
    // 首个渲染帧就落到正确位置（不播过渡），同时把角色对应的列表铺好
    this.sync(false)
  },

  pageLifetimes: {
    // 页面重新显示（含从其它 tab 切回被缓存的页面）时，位置必须立即纠正；
    // 角色也可能刚变过（切换身份后重新进 tab 页），所以列表在这里一并复核。
    show() {
      this.sync(false)
    }
  },

  methods: {
    // 当前页面在给定列表中的下标
    routeIndex(list) {
      const pages = getCurrentPages()
      const cur = pages[pages.length - 1]
      const route = cur && cur.route ? '/' + cur.route : ''
      const i = list.findIndex((it) => it.pagePath === route)
      return i >= 0 ? i : 0
    },

    // 把「列表 + 高亮」同步到当前角色与当前路由。anim=false 表示瞬移（禁过渡）。
    // 两件事合成一次 setData：换列表与移高亮都必须在同一帧内生效，
    // 分开写会出现「列表已换、高亮还停在旧下标」的中间帧。
    sync(anim) {
      const list = resolveList()
      const role = list === LIST_MANAGER ? 'manager' : 'collector'
      const i = this.routeIndex(list)
      if (
        this.data.role === role &&
        this.data.selected === i &&
        this.data.blobIdx === i &&
        this.data.anim === anim
      ) {
        return
      }
      this.setData({ role, list, trackW: 100 / list.length, selected: i, blobIdx: i, anim })
    },

    onTap(e) {
      const i = Number(e.currentTarget.dataset.i)
      const item = this.data.list[i]
      if (!item) return
      // 已在当前 tab：不重复跳转
      if (this.routeIndex(this.data.list) === i) {
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
