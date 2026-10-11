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

console.log('')
console.log(`检查完成：${errors.length} 个错误，${warns.length} 个警告`)
process.exit(errors.length ? 1 : 0)
