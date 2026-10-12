/**
 * 自定义 tabBar 单测（无需微信环境）：直接把 asr-miniprogram/custom-tab-bar/index.js
 * 装进 Node 跑生命周期，钉住两类行为：切页时序、以及**按角色渲染两套列表**。
 *
 * 背景 A —— 切页时序：自定义 tabBar 是「每个页面各有一个实例」，切 tab 时微信新建
 * 目标页实例、老实例随页面销毁，两块高亮块之间没有共享 DOM。原实现在新实例 attached
 * 里先把自己摆到「上一次所在的 tab」，再 32ms 后用 400ms 过渡滑到正确位置，于是：
 *   点击(t=0) → 老实例滑向目标 → 切换完成、新页已可见
 *   → 新实例首帧落在旧位置(错的) → 32ms 后开始滑 → 再 400ms 才到位
 * 页面早就切好了，高亮块还在路上（≈430ms）。
 * 修复后：新实例首个渲染帧就落在正确位置，且那一帧禁过渡（anim=false ⇒ .no-anim），
 * 位置变化永远「一帧到位」，过渡只留给点击离场那一次。
 *
 * 背景 B —— 按角色渲染：底部导航分两套（采集员 4 项 / 管理员 2 项），而项数变了，
 * 高亮块轨道宽（trackW = 100/项数）**必须跟着变**，否则高亮块会落偏。这一层最容易
 * 悄悄回归（列表改了忘记改宽度），所以单测同时钉住「列表 + 宽度」一起下发。
 *
 * 覆盖：
 *   1. 采集员：首帧落在正确位置，且 trackW=25（4 项）
 *   2. 管理员：列表换成 2 项、首帧落在正确位置，且 trackW=50
 *   3. 两套列表都保持 app.json 的相对顺序、无重复项
 *   4. attached 只 setData 一次、不注册任何延时回调（没有「先错后改」）
 *   5. 缓存页重新显示：立即纠正，且同样禁用过渡
 *   6. 角色变化后 show 复核：列表与宽度一起换掉
 *   7. 点击离场：anim=true，高亮指向目标（保留动效）
 *   8. 点当前 tab 不重复跳转；未知路由兜底为 0；switchTab 失败回滚高亮
 *
 * 用法：node tools/test_tabbar.js
 *      对照历史实现：TABBAR_SRC=<另一个 index.js 路径> node tools/test_tabbar.js
 */
const fs = require('fs')
const path = require('path')

const SRC =
  process.env.TABBAR_SRC ||
  path.join(__dirname, '..', 'asr-miniprogram', 'custom-tab-bar', 'index.js')
const src = fs.readFileSync(SRC, 'utf8')

let pass = 0
let fail = 0
function check(name, cond, extra = '') {
  if (cond) {
    pass++
    console.log('  PASS ' + name + (extra ? '  | ' + extra : ''))
  } else {
    fail++
    console.log('  FAIL ' + name + (extra ? '  | ' + extra : ''))
  }
}

let def = null
let curRoute = ''
let timers = []
let switched = []
let switchFail = false
let storage = {}

const wxMock = {
  switchTab(opt) {
    switched.push(opt.url)
    if (switchFail && opt.fail) opt.fail({})
  },
  nextTick(cb) {
    timers.push(cb)
  },
  // 组件用 Storage 作「角色」的跨启动兜底；globalData 为空时才会走到这里
  getStorageSync(k) {
    return storage[k] === undefined ? '' : storage[k]
  },
  setStorageSync(k, v) {
    storage[k] = v
  },
  showToast() {}
}
const getCurrentPagesMock = () => [{ route: curRoute.replace(/^\//, '') }]
// getApp() 必须返回**单例**：globalData 是跨实例共享的 —— 角色就从这里同步读，
// 每次新建对象会掩盖「角色没同步上」这个正是要验的行为。
const appMock = { globalData: { role: 'collector' } }

// 装载组件定义
new Function('Component', 'getApp', 'getCurrentPages', 'wx', 'setTimeout', src)(
  (d) => {
    def = d
  },
  () => appMock,
  getCurrentPagesMock,
  wxMock,
  (cb, ms) => {
    timers.push(cb)
    return timers.length
  }
)

// 挂载一个页面实例：data 从默认值深拷贝（模拟微信新建实例）
function mount(route) {
  curRoute = route
  const data = JSON.parse(JSON.stringify(def.data))
  const inst = {
    data,
    patches: [],
    setData(patch) {
      inst.patches.push(JSON.parse(JSON.stringify(patch)))
      Object.assign(inst.data, patch)
    }
  }
  Object.keys(def.methods || {}).forEach((k) => {
    inst[k] = def.methods[k].bind(inst)
  })
  // 生命周期挂在定义顶层（不在 methods 里），同样需要绑 this
  ;['created', 'attached', 'ready', 'detached'].forEach((k) => {
    if (typeof def[k] === 'function') inst[k] = def[k].bind(inst)
  })
  inst.pageLifetimes = {}
  Object.keys(def.pageLifetimes || {}).forEach((k) => {
    inst.pageLifetimes[k] = def.pageLifetimes[k].bind(inst)
  })
  return inst
}

const P = {
  home: '/pages/home/home',
  res: '/pages/resources/resources',
  rec: '/pages/record/record',
  me: '/pages/profile/profile'
}
// app.json 的 tabBar.list（组件必须保留全部 4 项，否则采集员切不过去）
const APP_TABS = [P.home, P.res, P.rec, P.me]

function asCollector() {
  appMock.globalData.role = 'collector'
}
function asManager() {
  appMock.globalData.role = 'admin'
}

console.log('[0] 组件定义与两套列表')
check('组件 data/methods 结构正确', !!def && !!def.data && !!def.methods)
const srcPaths = [...src.matchAll(/pagePath:\s*'([^']+)'/g)].map((m) => m[1])
const collector = srcPaths.slice(0, 4)
const manager = srcPaths.slice(4)
check('采集员列表 4 项', collector.length === 4, collector.join(' / '))
check('管理员列表 2 项（任务管理 / 个人中心）', manager.length === 2, manager.join(' / '))
check(
  '两套列表都保持 app.json 的相对顺序、无重复',
  (() => {
    const asc = (arr) => arr.every((p, i) => i === 0 || APP_TABS.indexOf(arr[i - 1]) < APP_TABS.indexOf(p))
    return (
      asc(collector) &&
      asc(manager) &&
      new Set(collector).size === 4 &&
      new Set(manager).size === 2 &&
      manager.every((p) => APP_TABS.includes(p))
    )
  })(),
  APP_TABS.join(',')
)
check('采集员那套覆盖 app.json 全部 4 项', collector.join(',') === APP_TABS.join(','))
check('默认 anim=false（首帧不播过渡）', def.data.anim === false, 'anim=' + def.data.anim)
check('默认列表即采集员那套（角色未知时不藏功能）', def.data.list.length === 4)

console.log('\n[1] 采集员首次进入「学习资源」（fresh 实例，默认值 selected=0/blobIdx=0）')
asCollector()
timers = []
const instRes = mount(P.res)
instRes.attached()
check('首帧高亮就在「学习资源」(idx=1)', instRes.data.blobIdx === 1 && instRes.data.selected === 1,
  'selected=' + instRes.data.selected + ', blobIdx=' + instRes.data.blobIdx)
check('轨道宽 trackW=25（4 项）', instRes.data.trackW === 25, 'trackW=' + instRes.data.trackW)
check('首帧 anim=false（纠正位置那一帧不滑）', instRes.data.anim === false, 'anim=' + instRes.data.anim)
check('attached 只 setData 一次（没有「先落到旧位置再改」）', instRes.patches.length === 1,
  JSON.stringify(instRes.patches))
check('attached 未注册任何延时回调（没有 32ms 后的补位）', timers.length === 0,
  'timers=' + timers.length)

console.log('\n[2] 管理员进入「个人中心」：列表应是 2 项、轨道宽 50%、落点 idx=1')
asManager()
timers = []
const instAdm = mount(P.me)
instAdm.attached()
check('列表宽度换成 2 项', instAdm.data.list.length === 2, instAdm.data.list.map((i) => i.text).join(' / '))
check('首帧高亮在「个人中心」(idx=1)', instAdm.data.blobIdx === 1 && instAdm.data.selected === 1,
  'selected=' + instAdm.data.selected)
check('轨道宽 trackW=50（2 项）', instAdm.data.trackW === 50, 'trackW=' + instAdm.data.trackW)
check('列表与宽度在同一次 setData 内下发', (() => {
  const p = instAdm.patches[0] || {}
  return p.list && p.trackW === 50
})(), JSON.stringify(instAdm.patches))
check('attached 只 setData 一次', instAdm.patches.length === 1, JSON.stringify(instAdm.patches))
check('未注册延时回调', timers.length === 0, 'timers=' + timers.length)

console.log('\n[3] 管理员进入「任务管理」：在第一项')
asManager()
const instAdmHome = mount(P.home)
instAdmHome.attached()
check('首帧高亮在「任务管理」(idx=0)', instAdmHome.data.blobIdx === 0 && instAdmHome.data.selected === 0,
  'selected=' + instAdmHome.data.selected)
check('列表仍是 2 项', instAdmHome.data.list.length === 2)
check('trackW 仍是 50', instAdmHome.data.trackW === 50, 'trackW=' + instAdmHome.data.trackW)

console.log('\n[4] 缓存页重新显示：上一项留在「个人中心」，页面仍是「任务管理」')
asManager()
const instHome = mount(P.home)
instHome.attached()
instHome.patches.length = 0
// 模拟用户此前从这里点走了：老实例把高亮推向过 idx=1
instHome.data.blobIdx = 1
instHome.data.selected = 1
instHome.data.anim = true
instHome.pageLifetimes.show()
check('show 后立即回到「任务管理」(idx=0)',
  instHome.data.blobIdx === 0 && instHome.data.selected === 0,
  'selected=' + instHome.data.selected + ', blobIdx=' + instHome.data.blobIdx)
check('show 时 anim=false（不是滑回来）', instHome.data.anim === false, 'anim=' + instHome.data.anim)
check('show 只 setData 一次', instHome.patches.length === 1, JSON.stringify(instHome.patches))

console.log('\n[5] 角色变化后 show 复核：列表与宽度必须一起换')
asManager()
const instRole = mount(P.me)
instRole.attached()
instRole.patches.length = 0
asCollector() // 切换身份（演示账号切换）后重新显示本页
instRole.pageLifetimes.show()
check('列表从 2 项换成 4 项', instRole.data.list.length === 4, instRole.data.list.map((i) => i.text).join(' / '))
check('轨道宽跟着换成 25', instRole.data.trackW === 25, 'trackW=' + instRole.data.trackW)
check('落点跟着换到「我的」(idx=3)', instRole.data.blobIdx === 3 && instRole.data.selected === 3,
  'selected=' + instRole.data.selected)
check('复核只 setData 一次', instRole.patches.length === 1, JSON.stringify(instRole.patches))

console.log('\n[6] 点击离场：保留动效（anim=true 指向目标）')
asCollector()
switched = []
const inst0 = mount(P.home)
inst0.attached()
inst0.patches.length = 0
inst0.onTap({ currentTarget: { dataset: { i: 2 } } })
check('点击后高亮立即指向「语言采集」(idx=2)',
  inst0.data.blobIdx === 2 && inst0.data.selected === 2,
  'selected=' + inst0.data.selected + ', blobIdx=' + inst0.data.blobIdx)
check('点击时 anim=true（这段过渡负责离场指向感）', inst0.data.anim === true, 'anim=' + inst0.data.anim)
check('发起了 switchTab 到目标页', switched[0] === P.rec, switched.join(','))

console.log('\n[7] 切页全链路：新实例首帧必须已到位（原实现在这里落后 ≈430ms）')
timers = []
asCollector()
const instRec = mount(P.rec)
instRec.attached()
check('目标页首帧高亮就在「语言采集」(idx=2)，无中间错位帧',
  instRec.data.blobIdx === 2 && instRec.data.selected === 2,
  'selected=' + instRec.data.selected + ', blobIdx=' + instRec.data.blobIdx)
check('目标页首帧 anim=false（不会从上一项滑过来）', instRec.data.anim === false)
check('目标页未注册延时回调（无 32ms 补位 + 400ms 滑动）', timers.length === 0, 'timers=' + timers.length)
check('到位不依赖任何延时：attached 后立即正确', instRec.patches.length === 1)

console.log('\n[8] 边界')
switched = []
const instSame = mount(P.rec)
instSame.attached()
instSame.onTap({ currentTarget: { dataset: { i: 2 } } })
check('点当前 tab 不重复跳转', switched.length === 0, switched.join(','))
check('点当前 tab 高亮仍在原位', instSame.data.blobIdx === 2)

curRoute = '/pages/unknown/unknown'
const instUnknown = mount('/pages/unknown/unknown')
instUnknown.attached()
check('未知路由兜底为 idx=0，不报错', instUnknown.data.blobIdx === 0 && instUnknown.data.selected === 0)

// 角色未知（既没 globalData 也没 Storage）：按采集员那套渲染，不把功能藏起来
appMock.globalData.role = ''
storage = {}
const instNoRole = mount(P.home)
instNoRole.attached()
check('角色未知时按采集员那套渲染（4 项）', instNoRole.data.list.length === 4,
  'len=' + instNoRole.data.list.length)

switchFail = true
const instFail = mount(P.home)
instFail.attached()
instFail.onTap({ currentTarget: { dataset: { i: 3 } } })
check('switchTab 失败后回滚到真实位置 (idx=0)',
  instFail.data.blobIdx === 0 && instFail.data.selected === 0,
  'selected=' + instFail.data.selected + ', blobIdx=' + instFail.data.blobIdx)
check('回滚时 anim=false（不滑回去）', instFail.data.anim === false)
switchFail = false

const instBad = mount(P.home)
check('非法下标不抛错', (() => {
  try {
    instBad.onTap({ currentTarget: { dataset: { i: 99 } } })
    return true
  } catch (e) {
    return false
  }
})())

console.log(`\n== 单测结果：${pass} passed, ${fail} failed ==`)
if (fail) process.exit(1)
