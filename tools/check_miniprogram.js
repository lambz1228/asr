/**
 * 小程序静态自检（无需微信开发者工具）：
 *   1. 所有 .ts 做语法校验（TypeScript transpileModule）
 *   2. 所有 .json 必须可解析
 *   3. app.json 中声明的页面 / 分包 / tabBar 资源必须真实存在
 *   4. 页面四件套（.ts/.wxml/.json）齐全
 *   5. 源码里出现的页面路径跳转必须指向已声明页面
 *
 * 用法：node tools/check_miniprogram.js
 * 说明：typescript 从 WorkBuddy 托管 node 工作区加载，避免项目内重复安装依赖。
 */
const fs = require('fs')
const path = require('path')

const TS_PATH =
  'C:/Users/Admin（无密码）/.workbuddy/binaries/node/workspace/node_modules/typescript'
const ROOT = path.join(__dirname, '..', 'asr-miniprogram')

let errors = []
let warns = []
const ok = (m) => console.log('  ok   ' + m)
const fail = (m) => {
  errors.push(m)
  console.log('  FAIL ' + m)
}
const warn = (m) => {
  warns.push(m)
  console.log('  warn ' + m)
}

function walk(dir, filter, out = []) {
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name)
    const st = fs.statSync(p)
    if (st.isDirectory()) {
      if (name === 'node_modules' || name === 'miniprogram_npm') continue
      walk(p, filter, out)
    } else if (filter(name)) {
      out.push(p)
    }
  }
  return out
}

const rel = (p) => path.relative(ROOT, p).replace(/\\/g, '/')

console.log('== 1. TypeScript 语法校验 ==')
const ts = require(TS_PATH)
const tsFiles = walk(ROOT, (n) => n.endsWith('.ts'))
for (const f of tsFiles) {
  const src = fs.readFileSync(f, 'utf8')
  const out = ts.transpileModule(src, {
    fileName: f,
    reportDiagnostics: true,
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS }
  })
  const diags = (out.diagnostics || []).filter((d) => d.category === 1) // Error
  if (diags.length) {
    for (const d of diags) {
      const pos = d.file ? d.file.getLineAndCharacterOfPosition(d.start) : { line: 0, character: 0 }
      fail(`${rel(f)}:${pos.line + 1}:${pos.character + 1} ${ts.flattenDiagnosticMessageText(d.messageText, ' ')}`)
    }
  } else {
    ok(rel(f))
  }
}

console.log('== 2. JSON 可解析 ==')
const jsonFiles = walk(ROOT, (n) => n.endsWith('.json'))
for (const f of jsonFiles) {
  try {
    JSON.parse(fs.readFileSync(f, 'utf8'))
    ok(rel(f))
  } catch (e) {
    fail(`${rel(f)} 解析失败：${e.message}`)
  }
}

console.log('== 3. app.json 页面 / 分包 / tabBar 资源 ==')
const app = JSON.parse(fs.readFileSync(path.join(ROOT, 'app.json'), 'utf8'))
const declared = []
for (const p of app.pages || []) declared.push(p)
for (const sp of app.subPackages || []) {
  for (const p of sp.pages) declared.push(`${sp.root}/${p}`)
}
const entry = path.join(ROOT, (app.pages[0] || '') + '.ts')
fs.existsSync(entry) ? ok('入口页 ' + app.pages[0]) : fail('入口页缺失：' + app.pages[0])

for (const p of declared) {
  const base = path.join(ROOT, p)
  for (const ext of ['.ts', '.wxml', '.json']) {
    if (fs.existsSync(base + ext)) ok(rel(base + ext))
    else fail(`页面文件缺失：${p}${ext}`)
  }
}

for (const item of (app.tabBar && app.tabBar.list) || []) {
  if (!declared.includes(item.pagePath)) fail(`tabBar 页面未在 pages 中声明：${item.pagePath}`)
  for (const key of ['iconPath', 'selectedIconPath']) {
    const icon = item[key]
    if (!icon) {
      warn(`tabBar ${item.text} 缺少 ${key}`)
      continue
    }
    fs.existsSync(path.join(ROOT, icon)) ? ok('icon ' + icon) : fail(`tabBar 图标缺失：${icon}`)
  }
}

// tabBar.custom = true 时必须提供 custom-tab-bar 组件，否则页面底部会没有导航
if (app.tabBar && app.tabBar.custom) {
  for (const ext of ['.js', '.json', '.wxml', '.wxss']) {
    const p = path.join(ROOT, 'custom-tab-bar', 'index' + ext)
    fs.existsSync(p) ? ok('custom-tab-bar ' + path.basename(p)) : fail(`自定义 tabBar 组件缺失：custom-tab-bar/index${ext}`)
  }
  const cbJson = path.join(ROOT, 'custom-tab-bar', 'index.json')
  if (fs.existsSync(cbJson)) {
    try {
      const j = JSON.parse(fs.readFileSync(cbJson, 'utf8'))
      j.component === true ? ok('custom-tab-bar 声明为组件') : fail('custom-tab-bar/index.json 缺少 "component": true')
    } catch (e) {
      fail('custom-tab-bar/index.json 解析失败：' + e.message)
    }
  }
  // 组件内引用的图标与类型定义必须同时存在于 tabBar.list
  const cbWxml = fs.readFileSync(path.join(ROOT, 'custom-tab-bar', 'index.wxml'), 'utf8')
  ;['activeIcon', 'icon'].forEach((k) => {
    cbWxml.includes(`item.${k}`) ? ok(`custom-tab-bar 使用 ${k}`) : warn(`custom-tab-bar 未使用 ${k}`)
  })

  // ---- tabBar 切页时序护栏（防「切界面时导航 UI 跟不上」回归）----
  // 自定义 tabBar 是每个页面各一个实例，切 tab 时目标页**新建**实例、老实例随页面销毁。
  // 所以新实例必须首个渲染帧就落在正确位置；一旦它「先落到上一次所在的 tab、再延时滑过来」，
  // 就会出现「页面已切好、高亮块还在路上」的滞后感（实测约 430ms）。
  const cbJs = fs.readFileSync(path.join(ROOT, 'custom-tab-bar', 'index.js'), 'utf8')
  const cbWxss = fs.readFileSync(path.join(ROOT, 'custom-tab-bar', 'index.wxss'), 'utf8')

  // 1) 不得再依赖「上一次所在的 tab」这种跨实例共享状态来定位
  cbJs.includes('tabIndex')
    ? fail('custom-tab-bar 仍在使用 globalData.tabIndex 回溯上一次所在的 tab（会让新实例首帧落在错位置）')
    : ok('custom-tab-bar 不依赖上一次所在的 tab 定位')

  // 2) 不得用延时回调「补位」高亮块
  ;/setTimeout\s*\(/.test(cbJs)
    ? fail('custom-tab-bar 存在 setTimeout 补位（会把高亮块拖到下一页面上再滑）')
    : ok('custom-tab-bar 无延时补位')

  // 3) 组件里是**两套列表**（采集员 4 项 / 管理员 2 项），两套都必须与 app.json 的
  //    tabBar.list 同序：顺序不一致会让高亮落点与 switchTab 目标错位。
  //    项数变了还必须同步改高亮块轨道宽（否则其中一套的高亮会落偏），所以一并钉住。
  //    ⚠️ app.json 必须保留全部 4 项 —— 只有声明在 tabBar.list 里的页面才能 switchTab，
  //    裁剪只发生在渲染层。
  const appPaths = (app.tabBar.list || []).map((i) => '/' + i.pagePath)
  const lists = {}
  for (const m of cbJs.matchAll(/const\s+LIST_([A-Z]+)\s*=\s*\[([\s\S]*?)\n\]/g)) {
    lists[m[1].toLowerCase()] = [...m[2].matchAll(/pagePath:\s*'([^']+)'/g)].map((x) => x[1])
  }
  const cbCollector = lists.collector || []
  const cbManager = lists.manager || []
  const ascInApp = (arr) =>
    arr.every((p, i) => i === 0 || appPaths.indexOf(arr[i - 1]) < appPaths.indexOf(p))
  const allInApp = (arr) => arr.length > 0 && arr.every((p) => appPaths.includes(p))

  cbCollector.length === 4 && cbManager.length === 2
    ? ok(`custom-tab-bar 两套列表项数正确（采集员 ${cbCollector.length} / 管理员 ${cbManager.length}）`)
    : fail(`custom-tab-bar 两套列表项数不对：采集员 ${cbCollector.length} 项、管理员 ${cbManager.length} 项（应为 4 / 2）`)

  allInApp(cbCollector) && ascInApp(cbCollector) && allInApp(cbManager) && ascInApp(cbManager)
    ? ok('custom-tab-bar 两套列表都与 app.json 同序')
    : fail(`custom-tab-bar 列表与 app.json 不一致：采集员 [${cbCollector.join(',')}] / 管理员 [${cbManager.join(',')}] / app.json [${appPaths.join(',')}]`)

  const covered = appPaths.every((p) => cbCollector.includes(p) || cbManager.includes(p))
  covered
    ? ok('两套列表合起来覆盖 app.json 全部 tab')
    : fail('两套列表没覆盖 app.json 里声明的 tab（漏掉的页面采集员切不过去）：' + appPaths.filter((p) => !cbCollector.includes(p) && !cbManager.includes(p)).join(','))

  // 高亮块轨道宽必须由列表长度算出 —— 写死在 wxss 里必然有一套落偏
  ;/trackW:\s*100\s*\/\s*list\.length/.test(cbJs)
    ? ok('高亮块轨道宽由列表长度算出（100 / list.length）')
    : fail('custom-tab-bar 的高亮块轨道宽没有跟列表长度联动，两套列表里必有一套落偏')
  cbWxml.includes('trackW')
    ? ok('custom-tab-bar wxml 内联 trackW')
    : fail('custom-tab-bar wxml 未内联 trackW（宽度写死在 wxss 里会落偏）')
  ;/\.blob-track\s*\{[^}]*width:/.test(cbWxss)
    ? fail('custom-tab-bar wxss 给 .blob-track 写死了 width（项数按角色变，宽度只能内联下发）')
    : ok('custom-tab-bar wxss 未写死轨道宽')

  // 角色必须**同步**可读，组件才可能在首帧决定渲染几项。
  // 行首必须带分号：上一句是三元表达式且不以分号结尾，否则这里的正则字面量
  // 会被 ASI 当成除法继续上一句（本项目已踩过一次，见档案 §2.2）。
  ;/globalData\.role|getStorageSync\('role'\)/.test(cbJs)
    ? ok('custom-tab-bar 的角色取自同步可读的位置（globalData / Storage）')
    : fail('custom-tab-bar 没有从同步位置读角色 —— 首帧等不了异步请求，会先渲染错的一套导航')

  // ---- 只服务采集员的页面必须有「管理员误入」拦截 ----
  // 语言采集 / 学习资源 不在管理员的导航里，但页面栈可能被恢复（DevTools 保留页面栈、
  // 热重载、演示切身份后回到旧页）。管理员一旦停在采集员版式的页面上，看到的是
  // 「导航栏写着语言采集、内容是当前身份无需采集」这种自相矛盾的屏 —— 就是「UI 切换混乱」。
  // 拦截必须能在**渲染之前**生效，所以要求用同步可读的角色（currentRole），
  // 而不是等 getMe 回来再跳。
  ;['pages/record/record', 'pages/resources/resources'].forEach((p) => {
    const tsPath = path.join(ROOT, p + '.ts')
    const ts = fs.existsSync(tsPath) ? fs.readFileSync(tsPath, 'utf8') : ''
    // 同步判断必须落在 onLoad 里（渲染之前）；只放在 load() 里会先闪一帧再跳
    const onLoadBlock = (ts.match(/onLoad\([\s\S]*?\n  \},/) || [''])[0]
    const syncGuard = /isManagerRole\(currentRole\(\)\)/.test(onLoadBlock)
    const bounce = /reLaunch/.test(ts) || /switchTab\([\s\S]{0,120}TAB\.home/.test(ts)
    syncGuard && bounce
      ? ok(`${p} 在 onLoad 里同步拦截管理员误入并弹回任务管理`)
      : fail(`${p} 缺少管理员误入拦截 —— 管理员可能停在采集员页面上；需要 onLoad 里 currentRole() 同步判断 + switchTab/reLaunch 回任务管理`)
  })

  // 4) 首帧必须禁过渡：anim 默认 false + wxml 绑 no-anim + wxss 关掉 transition
  ;/anim:\s*false/.test(cbJs)
    ? ok('custom-tab-bar anim 默认 false（首帧不播过渡）')
    : fail('custom-tab-bar 的 anim 默认值不是 false，首帧可能滑过来')
  cbWxml.includes('no-anim')
    ? ok('custom-tab-bar wxml 绑定 no-anim')
    : fail('custom-tab-bar wxml 未绑定 no-anim（首帧无法禁过渡）')
  ;/\.blob-track\.no-anim\s*\{[^}]*transition:\s*none/.test(cbWxss)
    ? ok('custom-tab-bar wxss 为 .no-anim 关闭 transition')
    : fail('custom-tab-bar wxss 未为 .no-anim 关闭 transition')
}

console.log('== 4. 源码内页面跳转路径 ==')
// 只校验 wx.navigateTo / redirectTo / reLaunch / switchTab 的 url，
// 避免把 wx.request 的后端接口路径误判成页面
const NAV_RE = /wx\.(navigateTo|redirectTo|reLaunch|switchTab)\(\s*\{[^}]*?url:\s*['"`]([^'"`]+)/g
const routeRefs = walk(ROOT, (n) => n.endsWith('.ts'))
let navCount = 0
for (const f of routeRefs) {
  const src = fs.readFileSync(f, 'utf8')
  let m
  while ((m = NAV_RE.exec(src))) {
    navCount += 1
    const target = m[2].replace(/^\//, '').replace(/\?.*$/, '')
    if (!declared.includes(target)) fail(`${rel(f)} 跳转到未声明的页面：/${target}`)
  }
}
ok(`wx.* 跳转检查完成（${navCount} 处）`)

// utils/nav.ts 里的 TAB 常量是跳转路径的单一来源，单独校验
const navSrc = fs.readFileSync(path.join(ROOT, 'utils/nav.ts'), 'utf8')
const tabRe = /(home|resources|record|profile):\s*'([^']+)'/g
let tm
let tabCount = 0
while ((tm = tabRe.exec(navSrc))) {
  tabCount += 1
  const target = tm[2].replace(/^\//, '')
  if (!declared.includes(target)) fail(`utils/nav.ts TAB.${tm[1]} 指向未声明的页面：${tm[2]}`)
  else if (!((app.tabBar && app.tabBar.list) || []).some((i) => i.pagePath === target))
    fail(`utils/nav.ts TAB.${tm[1]} 不是 tabBar 页面：${tm[2]}`)
}
tabCount === 4 ? ok('TAB 常量均为 tabBar 页面') : fail(`TAB 常量数量异常：${tabCount}`)

console.log('== 5. WXML 标签闭合 ==')
// 先把 {{ }} 表达式整体摘掉（里面可能含 <= && 等 XML 非法字符），再做标签配对
const wxmlFiles = walk(ROOT, (n) => n.endsWith('.wxml'))
const SELF_CLOSE = new Set(['image', 'input', 'icon', 'progress', 'import', 'include', 'wxs'])
for (const f of wxmlFiles) {
  const src = fs
    .readFileSync(f, 'utf8')
    .replace(/\{\{[\s\S]*?\}\}/g, 'X')
    .replace(/<!--[\s\S]*?-->/g, '')
  const stack = []
  let problem = ''
  const tagRe = /<\/?([a-zA-Z][a-zA-Z0-9-]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>/g
  let m
  while ((m = tagRe.exec(src))) {
    const raw = m[0]
    const tag = m[1]
    if (raw.startsWith('</')) {
      const top = stack.pop()
      if (top !== tag) {
        problem = `</${tag}> 与 <${top || '无'}> 不匹配`
        break
      }
    } else if (!raw.endsWith('/>') && !SELF_CLOSE.has(tag)) {
      stack.push(tag)
    }
  }
  if (!problem && stack.length) problem = `未闭合标签：<${stack.join('>, <')}>`
  problem ? fail(`${rel(f)} ${problem}`) : ok(rel(f))
}

console.log('== 6. WXML 里字面量 class 必须有样式定义 ==')
// 只检查不带 {{ }} 的字面量 class（条件类名由数据驱动，无法静态判定）
const styleFiles = walk(ROOT, (n) => n.endsWith('.wxss'))
const definedClasses = new Set()
for (const f of styleFiles) {
  for (const m of fs.readFileSync(f, 'utf8').matchAll(/\.([a-zA-Z][a-zA-Z0-9_-]*)/g)) {
    definedClasses.add(m[1])
  }
}
let orphanCount = 0
for (const f of walk(ROOT, (n) => n.endsWith('.wxml'))) {
  const src = fs.readFileSync(f, 'utf8').replace(/\{\{[\s\S]*?\}\}/g, ' ')
  for (const m of src.matchAll(/class="([^"]*)"/g)) {
    for (const token of m[1].split(/\s+/).filter(Boolean)) {
      if (!/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(token)) continue
      if (!definedClasses.has(token)) {
        orphanCount += 1
        warn(`${rel(f)} 使用了未定义的 class：${token}`)
      }
    }
  }
}
orphanCount === 0 ? ok(`class 全部有样式定义（共 ${definedClasses.size} 个类名）`) : null

console.log('== 7. WXSS 兼容性（calc 单位混用 / flex gap / 底部留白兜底） ==')
// 这三类写法在小程序里都会「看起来能编译、真机上布局却不对」：
//   a) calc() 里混用 % 与 rpx：rpx 折算取整后，两个 50% 卡 + 间距会超过 100%，
//      flex 提前换行 —— 两列布局退化成单列（症状：每行只有一张卡、右侧空一条）。
//   b) flex 容器用 gap：iOS 13 及更早的 WKWebView 不支持，间距整体消失。
//   c) padding/margin 简写里塞 env()：一旦该条被机型丢弃，整条简写（含左右内边距）一起失效。
for (const f of styleFiles) {
  const raw = fs
    .readFileSync(f, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' ')) // 注释挖空但保留行号
  const lines = raw.split(/\r?\n/)
  let sel = ''
  let isFlex = false
  for (let i = 0; i < lines.length; i++) {
    const text = lines[i].trim()
    if (!text) continue
    if (text.endsWith('{')) {
      sel = text.slice(0, -1).trim()
      isFlex = false
      continue
    }
    if (text === '}') {
      sel = ''
      isFlex = false
      continue
    }
    for (const m of text.matchAll(/calc\(([^)]*)\)/g)) {
      if (m[1].includes('%') && /rpx/.test(m[1])) {
        fail(`${rel(f)}:${i + 1} calc() 里混用 % 与 rpx（${sel}）——rpx 取整会让换行提前，两列会退化成单列：${text}`)
      }
    }
    if (/^display:\s*flex/.test(text)) isFlex = true
    if (/^(row-|column-)?gap:/.test(text) && isFlex) {
      warn(`${rel(f)}:${i + 1} flex 容器用了 gap（${sel}）——iOS 13 及更早不支持，间距会消失`)
    }
    if (/^(padding|margin):/.test(text) && /env\(/.test(text)) {
      warn(`${rel(f)}:${i + 1} ${sel} 的 ${text.split(':')[0]} 简写里含 env()，建议拆出独立的 padding-bottom 兜底：${text}`)
    }
  }
}
ok(`WXSS 兼容性检查完成（${styleFiles.length} 个文件）`)

console.log('== 8. 缓存层接入与 setData 数据量护栏 ==')
// 背景：每个 tab 页 onShow 都会重新拉数据，如果绕过缓存层直接 request，
// 就会退化成「请求 → 骨架闪 → 全量重渲染」的循环（切 tab 卡顿的主因）。
// 同样地，把上千条任务直接放进 data 再 setData，是另一个主要卡顿源。
const CACHE_FILE = path.join(ROOT, 'utils', 'cache.ts')
if (!fs.existsSync(CACHE_FILE)) {
  fail('缺少 utils/cache.ts（数据缓存层）——tab 页会退化成每次 onShow 全量重拉')
} else {
  const src = fs.readFileSync(CACHE_FILE, 'utf8')
  for (const api of ['readCache', 'writeCache', 'cachedFetch', 'fetchOnce', 'invalidate']) {
    src.includes('export function ' + api)
      ? ok(`cache.ts 导出 ${api}`)
      : fail(`cache.ts 缺少 ${api} 导出`)
  }
  // 并发去重：同 key 的并发请求必须合并，否则多页同时 getMe 会各发一次
  /inflight/.test(src) ? ok('cache.ts 含并发去重（inflight）') : fail('cache.ts 未实现并发去重')
}

const TAB_PAGES = ['home', 'resources', 'record', 'profile']
for (const name of TAB_PAGES) {
  const f = path.join(ROOT, 'pages', name, name + '.ts')
  if (!fs.existsSync(f)) {
    fail(`缺少 tab 页 ${name}`)
    continue
  }
  const src = fs.readFileSync(f, 'utf8')
  if (!/from '\.\.\/\.\.\/utils\/cache'/.test(src)) {
    fail(`pages/${name}/${name}.ts 未接入 utils/cache —— 每次切回本页都会重新请求并闪骨架`)
    continue
  }
  // 用 readCache / hasCache 判断「有缓存 → 不铺骨架」，避免切 tab 时白屏闪一下
  /readCache\(|hasCache\(/.test(src)
    ? ok(`pages/${name} 已按缓存命中情况决定是否铺骨架`)
    : warn(`pages/${name} 未用 readCache/hasCache 判断首屏，可能仍会在切 tab 时闪骨架`)
}

// 全量列表必须放页面实例属性，不能进 data（约定：data 里不许出现 allXxx 数组）
for (const f of walk(ROOT, (n) => n.endsWith('.wxml'))) {
  const src = fs.readFileSync(f, 'utf8')
  for (const m of src.matchAll(/wx:for="\{\{\s*([A-Za-z_$][\w$]*)/g)) {
    if (/^all[A-Z]/.test(m[1])) {
      fail(`${rel(f)} 把全量数组 ${m[1]} 绑到了 wx:for —— 应只 setData 渲染所需的条数（见 pages/home 注释）`)
    }
  }
}
ok('全量数组未直接进入 data / wx:for')

console.log('== 9. 视觉令牌对齐（字号 / 圆角 / 颜色一律引用 app.wxss 令牌） ==')
// 令牌只在 app.wxss 定义，页面只引用。硬编码会让「改一处、全局生效」失效，
// 管理端分包页历史上就是这样悄悄退回旧 Vant 色板（#1989fa/#e64340/#f5f5f5/#999…）。
// 这些字面量是刻意的亮度斜坡 / 一次性装饰色，收敛会破坏原效果，故白名单放行；
// 清单与 tools/audit_ui_tokens.py 的 INTENTIONAL 保持一致。
const ALLOWED_HEX = new Set([
  '#3ea3ff', '#6dc4ff', // 首页/资源页头部三段渐变的中间与末端斜坡
  '#fffaf0', // 琥珀渐变亮端
  '#e9f3ff', '#f4f8fd', // 登录页背景三段渐变
  '#eef6ff', '#ddeafc', // 资源页卡片渐变两端
  '#a9741f', '#d9a44e', // 公告面板琥珀文字阶梯
  '#b7e4cb', // 同意书主按钮禁用态浅绿
])
const appWxssSrc = fs.readFileSync(path.join(ROOT, 'app.wxss'), 'utf8')
const fsTokens = [...appWxssSrc.matchAll(/--(fs-\d+)\s*:/g)].map((m) => m[1])
fsTokens.length >= 15
  ? ok(`字号阶梯已定义 ${fsTokens.length} 档（--fs-1 … --fs-${fsTokens.length}）`)
  : fail(`app.wxss 字号阶梯只有 ${fsTokens.length} 档，应至少 15 档（--fs-1 … --fs-15）`)

let tokenIssues = 0
for (const f of styleFiles) {
  if (rel(f) === 'app.wxss') continue
  const raw = fs
    .readFileSync(f, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
  const where = (i) => `${rel(f)}:${i}`
  const lines = raw.split(/\r?\n/)
  lines.forEach((line, idx) => {
    const t = line.trim()
    // 字号：只接受 var(--fs-N)。裸令牌名（如 `font-size: --fs-8`）是无效 CSS，
    // 会让字号静默退回默认值 —— 必须按错误拦下，不能只看有没有 rpx 字面量。
    const fsM = t.match(/^font-size:\s*(.+);$/)
    if (fsM && !/^var\(--fs-\d+\)$/.test(fsM[1])) {
      tokenIssues += 1
      fail(`${where(idx + 1)} font-size 未走令牌（${fsM[1]}）—— 必须写成 var(--fs-N)`)
    }
    // 圆角：var(--r-*) / 纯百分比 / 全 0 三种合法，其余（含裸 --r-*）一律报错
    const rM = t.match(/^border-radius:\s*(.+);$/)
    if (rM) {
      const v = rM[1].trim()
      const parts = v.split(/\s+/)
      // 合法：单值 var(--r-*)、纯百分比（圆形/胶囊）、或由 0 与 var(--r-*) 组成的多值
      const okToken = parts.every((p) => p === '0' || /^var\(--r-[a-z]+\)$/.test(p))
      const okPct = /^[0-9.]+%([ ]+[0-9.]+%)*$/.test(v)
      if (!okToken && !okPct) {
        tokenIssues += 1
        fail(`${where(idx + 1)} border-radius 未走令牌（${v}）—— 必须写成 var(--r-*)`)
      }
    }
    for (const m of t.matchAll(/#[0-9a-fA-F]{3,8}\b/g)) {
      if (!ALLOWED_HEX.has(m[0].toLowerCase())) {
        tokenIssues += 1
        fail(`${where(idx + 1)} 出现未令牌化的色值 ${m[0]} —— 请改用 var(--token)，或加入白名单并写明理由`)
      }
    }
    // 「实心品牌色」渐变全仓只允许一种拼写：135deg, var(--brand-lt) -> var(--brand)。
    // 这条规矩写在档案 §2.2 里但一直没有强制，实测已漂出两套其它写法：
    //   var(--brand), var(--brand-2)   方向相反（亮端在右下）
    //   var(--brand-2), var(--brand)   亮端用了 --brand-2 而非 --brand-lt
    // 只约束 135deg 的两段式；90deg/180deg 的进度条渐变、以及多段头部斜坡
    // （如 `var(--brand) 0%, #3ea3ff 52%, …`）语义不同，不在本条范围内。
    // 注意 `var(--brand-lt)` 不会被下面的模式匹配到（`--brand` 之后紧跟 `-lt`），
    // 所以正确写法天然豁免，无需再加例外。
    const brandGrad = /linear-gradient\(\s*135deg\s*,\s*var\(--brand(?:-2)?\)\s*,\s*var\(--brand(?:-2)?\)\s*\)/
    if (brandGrad.test(t)) {
      tokenIssues += 1
      fail(`${where(idx + 1)} 实心品牌色渐变拼写不统一（${t.match(brandGrad)[0].replace(/\s+/g, ' ')}）`
        + ' —— 统一写 linear-gradient(135deg, var(--brand-lt), var(--brand))')
    }
  })
}
tokenIssues === 0 ? ok('字号 / 圆角 / 颜色已全部走设计令牌') : null

console.log('')
console.log(`检查完成：${errors.length} 个错误，${warns.length} 个警告`)
process.exit(errors.length ? 1 : 0)
