/**
 * 缓存层单测（无需微信环境）：
 * 直接把 asr-miniprogram/utils/cache.ts 转成 JS 在 Node 里跑，验证四条语义：
 *   1. 并发去重   —— 同 key 并发只发一次请求（多页同时 getMe 只发一个）
 *   2. TTL 命中   —— 有效期内重复调用不再请求
 *   3. 过期回旧值 —— 命中旧值时立刻返回旧值，并后台静默刷新
 *   4. 代际失效   —— 整表 invalidate 期间在途的请求不写回缓存（换身份不串数据）
 * 以及一个「切 tab 场景」的请求数对比（有缓存 vs 无缓存）。
 *
 * 用法：node tools/test_cache.js
 */
const fs = require('fs')
const path = require('path')

const TS_PATH =
  'C:/Users/Admin（无密码）/.workbuddy/binaries/node/workspace/node_modules/typescript'
const CACHE_TS = path.join(__dirname, '..', 'asr-miniprogram', 'utils', 'cache.ts')

const ts = require(TS_PATH)
const src = fs.readFileSync(CACHE_TS, 'utf8')
const js = ts.transpileModule(src, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS }
}).outputText

const mod = { exports: {} }
new Function('exports', 'module', 'require', js)(mod.exports, mod, require)
const cache = mod.exports

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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

;(async () => {
  const { cachedFetch, invalidate, readCache, hasCache, fetchOnce } = cache

  // ---------------------------------------------------------------- 1. 并发去重
  console.log('[1] 并发去重：同 key 并发只发一次请求')
  let calls = 0
  const slow = () =>
    new Promise((r) =>
      setTimeout(() => {
        calls++
        r({ list: ['a'] })
      }, 20)
    )
  const [r1, r2, r3] = await Promise.all([
    cachedFetch('dup', 1000, slow),
    cachedFetch('dup', 1000, slow),
    cachedFetch('dup', 1000, slow)
  ])
  check('三个并发调用只触发 1 次请求（原本 3 次）', calls === 1, `实际 ${calls} 次`)
  check('三个并发调用都拿到同一份数据', r1.data.list[0] === 'a' && r2.data.list[0] === 'a' && r3.data.list[0] === 'a')
  check('首次调用标记为非缓存来源', r1.fromCache === false)

  // ---------------------------------------------------------------- 2. TTL 命中
  console.log('[2] TTL 内重复调用不再请求')
  calls = 0
  await cachedFetch('ttl', 200, () => (calls++, Promise.resolve(1)))
  await cachedFetch('ttl', 200, () => (calls++, Promise.resolve(1)))
  const r4 = await cachedFetch('ttl', 200, () => (calls++, Promise.resolve(1)))
  check('一次请求 + 两次命中 = 只发 1 次', calls === 1, `实际 ${calls} 次`)
  check('命中缓存时 fromCache=true', r4.fromCache === true)

  // ---------------------------------------------------------------- 3. 过期回旧值 + 后台刷新
  console.log('[3] 过期：先回旧值，再后台静默刷新')
  calls = 0
  await cachedFetch('stale', 30, () => (calls++, Promise.resolve({ v: calls })))
  await sleep(60)
  let refreshed = null
  const r5 = await cachedFetch(
    'stale',
    30,
    () => (calls++, Promise.resolve({ v: calls })),
    (fresh) => {
      refreshed = fresh
    }
  )
  check('过期时立即返回旧值（不阻塞页面）', r5.data.v === 1 && r5.fromCache === true, JSON.stringify(r5))
  check('过期时标记 revalidating=true', r5.revalidating === true)
  await sleep(30)
  check('后台静默刷新已触发 onRefresh', refreshed !== null && refreshed.v === 2, JSON.stringify(refreshed))
  check('刷新后缓存被替换为新值', readCache('stale').value.v === 2)

  // 后台刷新失败不能影响已渲染的旧值
  console.log('[3b] 后台刷新失败：旧值保留、不抛错')
  invalidate('boom')
  await cachedFetch('boom', 10, () => Promise.resolve({ ok: true }))
  await sleep(30)
  let threw = false
  const r6 = await cachedFetch('boom', 10, () => Promise.reject(new Error('后端挂了'))).catch(() => {
    threw = true
    return null
  })
  check('刷新失败不向调用方抛错', threw === false && r6 && r6.data.ok === true, JSON.stringify(r6))
  await sleep(20)
  check('刷新失败后旧值仍在缓存里', hasCache('boom') && readCache('boom').value.ok === true)

  // ---------------------------------------------------------------- 4. 代际失效
  console.log('[4] 整表 invalidate 期间在途的请求不写回缓存')
  invalidate()
  let resolveLate
  const lateP = new Promise((r) => {
    resolveLate = r
  })
  const p = cachedFetch('late', 10000, () => lateP)
  invalidate() // 模拟「切换身份」发生在请求返回之前
  resolveLate({ role: 'admin' })
  await p
  await sleep(10)
  check('在途请求返回后不会污染新身份的缓存', !hasCache('late'))

  // ---------------------------------------------------------------- 5. 切 tab 场景
  console.log('[5] 场景对比：来回切 5 次 tab（首页 4 个接口 + 采集页共用 /tasks）')
  const ENDPOINTS = ['me', 'progress', 'tasks', 'tasks/pool']
  function makeEnv() {
    const hits = { n: 0 }
    const fetchers = {}
    for (const k of ENDPOINTS) {
      fetchers[k] = () => {
        hits.n++
        return Promise.resolve({ k })
      }
    }
    return { hits, fetchers }
  }
  // 有缓存层
  const withCache = makeEnv()
  const pageShowCached = () =>
    Promise.all(ENDPOINTS.map((k) => cachedFetch(k, 15000, withCache.fetchers[k])))
  for (let i = 0; i < 5; i++) await pageShowCached() // 进入首页 5 次
  // 无缓存层（等价于每次 onShow 直接 request）
  const noCache = makeEnv()
  const pageShowPlain = () => Promise.all(ENDPOINTS.map((k) => noCache.fetchers[k]()))
  for (let i = 0; i < 5; i++) await pageShowPlain()

  check(
    '切 5 次首页：请求数从 20 降到 4',
    withCache.hits.n === 4 && noCache.hits.n === 20,
    `有缓存 ${withCache.hits.n} 次 / 无缓存 ${noCache.hits.n} 次`
  )

  console.log('')
  console.log(`== 缓存层单测：${pass} passed, ${fail} failed ==`)
  if (fail) process.exit(1)
})()
