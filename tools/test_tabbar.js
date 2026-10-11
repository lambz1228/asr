/**
 * 自定义 tabBar 切页时序单测（无需微信环境）：
 * 直接把 asr-miniprogram/custom-tab-bar/index.js 装进 Node 跑生命周期，
 * 复现「切界面时导航 UI 跟不上」的场景并钉住修复。
 *
 * 背景：自定义 tabBar 是「每个页面各有一个实例」，切 tab 时微信新建目标页实例、
 * 老实例随页面销毁，两块高亮块之间没有共享 DOM。原实现在新实例 attached 里
 * 先把自己摆到「上一次所在的 tab」，再 32ms 后用 400ms 过渡滑到正确位置，于是：
 *   点击(t=0) → 老实例滑向目标 → 切换完成、新页已可见
 *   → 新实例首帧落在旧位置(错的) → 32ms 后开始滑 → 再 400ms 才到位
 * 页面早就切好了，高亮块还在路上（≈430ms）。
 *
 * 修复后：新实例首个渲染帧就落在正确位置，且那一帧禁过渡（anim=false ⇒ .no-anim），
 * 位置变化永远是「一帧到位」，过渡只留给点击离场那一次。
 *
 * 覆盖：
 *   1. 首帧落在正确位置（不是 0，也不是上一次所在的 tab）
 *   2. 首帧 anim=false（否则纠正位置那一帧会滑 400ms）
 *   3. attached 只 setData 一次、不注册任何延时回调（没有「先错后改」）
 *   4. 缓存页重新显示：立即纠正，且同样禁用过渡
 *   5. 点击离场：anim=true，高亮指向目标（保留动效）
 *   6. 点当前 tab 不重复跳转；未知路由兜底为 0；switchTab 失败回滚高亮
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

const wxMock = {
  switchTab(opt) {
    switched.push(opt.url)
    if (switchFail && opt.fail) opt.fail({})
  },
  nextTick(cb) {
    timers.push(cb)
  },
  showToast() {}
}
const getCurrentPagesMock = () => [{ route: curRoute.replace(/^\//, '') }]
// getApp() 必须返回**单例**：globalData 是跨实例共享的，
// 每次新建对象会掩盖「新实例读到上一次所在 tab」这个正是要验的行为。
const appMock = { globalData: {} }

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

const TAB = {
  home: '/pages/home/home',
  res: '/pages/resources/resources',
  rec: '/pages/record/record',
  me: '/pages/profile/profile'
}

console.log('[0] 组件定义与 tab 顺序')
check('组件 data/methods 结构正确', !!def && !!def.data && !!def.methods)
check('4 个 tab 已声明', def.data.list.length === 4, def.data.list.map((i) => i.text).join(' / '))
check(
  'tab 顺序与 app.json 一致（首页/学习资源/语言采集/我的）',
  def.data.list.map((i) => i.pagePath).join(',') ===
    [TAB.home, TAB.res, TAB.rec, TAB.me].join(','),
  def.data.list.map((i) => i.pagePath).join(',')
)
check('默认 anim=false（首帧不播过渡）', def.data.anim === false, 'anim=' + def.data.anim)

console.log('\n[1] 首次进入「学习资源」（fresh 实例，默认值 selected=0/blobIdx=0）')
timers = []
const instRes = mount(TAB.res)
instRes.attached()
check('首帧高亮就在「学习资源」(idx=1)', instRes.data.blobIdx === 1 && instRes.data.selected === 1,
  'selected=' + instRes.data.selected + ', blobIdx=' + instRes.data.blobIdx)
check('首帧 anim=false（纠正位置那一帧不滑）', instRes.data.anim === false, 'anim=' + instRes.data.anim)
check('attached 只 setData 一次（没有「先落到旧位置再改」）', instRes.patches.length === 1,
  JSON.stringify(instRes.patches))
check('attached 未注册任何延时回调（没有 32ms 后的补位）', timers.length === 0,
  'timers=' + timers.length)

console.log('\n[2] 缓存页重新显示：上一项留在「学习资源」，页面仍是「首页」')
const instHome = mount(TAB.home)
instHome.attached()
instHome.patches.length = 0
// 模拟用户此前从这里点走了：老实例把高亮推向过 idx=1
instHome.data.blobIdx = 1
instHome.data.selected = 1
instHome.data.anim = true
instHome.pageLifetimes.show()
check('show 后立即回到「首页」(idx=0)',
  instHome.data.blobIdx === 0 && instHome.data.selected === 0,
  'selected=' + instHome.data.selected + ', blobIdx=' + instHome.data.blobIdx)
check('show 时 anim=false（不是滑回来）', instHome.data.anim === false, 'anim=' + instHome.data.anim)
check('show 只 setData 一次', instHome.patches.length === 1, JSON.stringify(instHome.patches))

console.log('\n[3] 点击离场：保留动效（anim=true 指向目标）')
switched = []
const inst0 = mount(TAB.home)
inst0.attached()
inst0.patches.length = 0
inst0.onTap({ currentTarget: { dataset: { i: 2 } } })
check('点击后高亮立即指向「语言采集」(idx=2)',
  inst0.data.blobIdx === 2 && inst0.data.selected === 2,
  'selected=' + inst0.data.selected + ', blobIdx=' + inst0.data.blobIdx)
check('点击时 anim=true（这段过渡负责离场指向感）', inst0.data.anim === true, 'anim=' + inst0.data.anim)
check('发起了 switchTab 到目标页', switched[0] === TAB.rec, switched.join(','))

console.log('\n[4] 切页全链路：新实例首帧必须已到位（原实现在这里落后 ≈430ms）')
// 目标页新实例：微信新建，data 回到默认值 0
timers = []
const instRec = mount(TAB.rec)
instRec.attached()
check('目标页首帧高亮就在「语言采集」(idx=2)，无中间错位帧',
  instRec.data.blobIdx === 2 && instRec.data.selected === 2,
  'selected=' + instRec.data.selected + ', blobIdx=' + instRec.data.blobIdx)
check('目标页首帧 anim=false（不会从上一项滑过来）', instRec.data.anim === false)
check('目标页未注册延时回调（无 32ms 补位 + 400ms 滑动）', timers.length === 0, 'timers=' + timers.length)
check('到位不依赖任何延时：attached 后立即正确', instRec.patches.length === 1)

console.log('\n[5] 边界')
switched = []
const instSame = mount(TAB.rec)
instSame.attached()
instSame.onTap({ currentTarget: { dataset: { i: 2 } } })
check('点当前 tab 不重复跳转', switched.length === 0, switched.join(','))
check('点当前 tab 高亮仍在原位', instSame.data.blobIdx === 2)

curRoute = '/pages/unknown/unknown'
const instUnknown = mount('/pages/unknown/unknown')
instUnknown.attached()
check('未知路由兜底为 idx=0，不报错', instUnknown.data.blobIdx === 0 && instUnknown.data.selected === 0)

switchFail = true
const instFail = mount(TAB.home)
instFail.attached()
instFail.onTap({ currentTarget: { dataset: { i: 3 } } })
check('switchTab 失败后回滚到真实位置 (idx=0)',
  instFail.data.blobIdx === 0 && instFail.data.selected === 0,
  'selected=' + instFail.data.selected + ', blobIdx=' + instFail.data.blobIdx)
check('回滚时 anim=false（不滑回去）', instFail.data.anim === false)
switchFail = false

const instBad = mount(TAB.home)
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
