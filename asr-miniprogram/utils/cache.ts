// ============================================================================
// 轻量数据缓存层
// ----------------------------------------------------------------------------
// 解决的问题：每个 tab 页 onShow 都重新拉一遍接口（首页一次要 /auth/me、
// /progress、/tasks、/tasks/pool 四个请求），请求返回前整页停在骨架屏，
// 返回后又把上千条数据整体 setData 一次 —— 来回切 tab 就是「请求 → 骨架闪 →
// 全量重渲染」的循环，观感上就是卡、不流畅。
//
// 这层提供三件事：
//   1. 内存 TTL 缓存：命中即同步返回，页面「缓存直出」不再闪骨架；
//   2. 并发去重：同一个 key 的并发请求合并为一次（多页同时 getMe 只发一个）；
//   3. stale-while-revalidate：命中旧值时先把旧值交给页面渲染，
//      再后台静默拉新并在拿到后回调刷新，界面不阻塞、数据也不发霉。
//
// 注意：缓存只活在内存中（本次小程序生命周期内），不落 Storage。
// 这样不会出现「重启后读到过期脏数据」的问题，符合弱网/离线场景的预期。
// ============================================================================

type Fetcher<T> = () => Promise<T>

interface Entry {
  value: any
  /** 写入时间戳（ms） */
  at: number
  /** 有效期（ms） */
  ttl: number
}

export interface CachedResult<T> {
  data: T
  /** true 表示数据直接来自缓存（页面据此跳过骨架屏） */
  fromCache: boolean
  /** true 表示命中但已过 TTL，正在后台刷新 */
  revalidating: boolean
}

const store: Record<string, Entry> = {}
const inflight: Record<string, Promise<any>> = {}

// 代际号：整表失效（登录 / 退出 / 切换身份）时自增。
// 在此前发起、之后才返回的请求不再写回缓存，避免旧身份的响应污染新身份的数据。
let epoch = 0

/** 同步读取缓存（不管是否过期），供页面判断「能否缓存直出」 */
export function readCache<T = any>(key: string): { value: T; fresh: boolean } | null {
  const e = store[key]
  if (!e) return null
  return { value: e.value as T, fresh: Date.now() - e.at <= e.ttl }
}

/** 是否已有该 key 的缓存（含过期值） */
export function hasCache(key: string): boolean {
  return !!store[key]
}

export function writeCache(key: string, value: any, ttl: number) {
  store[key] = { value, at: Date.now(), ttl }
}

/**
 * 失效缓存。
 * - invalidate()            清空全部（登录 / 退出 / 切换身份后调用，角色变了所有数据都不可信）
 * - invalidate('tasks')     清掉 tasks 与其子键 tasks/pool
 */
export function invalidate(prefix?: string) {
  if (!prefix) {
    epoch++
    Object.keys(store).forEach((k) => delete store[k])
    return
  }
  Object.keys(store).forEach((k) => {
    if (k === prefix || k.indexOf(prefix + '/') === 0 || k.indexOf(prefix + '?') === 0) {
      delete store[k]
    }
  })
}

/**
 * 并发去重：同一 key 正在请求时，后续调用复用同一个 Promise。
 * 请求结束（无论成败）后立即释放，避免失败被永久缓存。
 */
export function fetchOnce<T>(key: string, fetcher: Fetcher<T>): Promise<T> {
  const running = inflight[key]
  if (running) return running as Promise<T>
  const p = fetcher().then(
    (v) => {
      delete inflight[key]
      return v
    },
    (e) => {
      delete inflight[key]
      throw e
    }
  )
  inflight[key] = p
  return p
}

/**
 * 缓存优先取数。
 *
 * - 未命中：等网络 → 写缓存 → 返回 { fromCache:false }
 * - 命中且新鲜：直接返回 { fromCache:true }，不发请求
 * - 命中但过期：立刻返回 { fromCache:true, revalidating:true }，
 *   同时后台刷新，成功后除了写缓存还会调用 onRefresh(newData) 让页面静默更新
 *
 * @param onRefresh 后台刷新成功后的回调（页面在此处 setData 更新视图）
 */
export function cachedFetch<T>(
  key: string,
  ttl: number,
  fetcher: Fetcher<T>,
  onRefresh?: (data: T) => void
): Promise<CachedResult<T>> {
  const hit = readCache<T>(key)
  if (hit) {
    if (!hit.fresh) {
      // 后台静默刷新：失败不影响已渲染的旧数据，也不弹错
      const gen = epoch
      fetchOnce(key, fetcher)
        .then((fresh) => {
          if (gen !== epoch) return
          writeCache(key, fresh, ttl)
          if (onRefresh) onRefresh(fresh)
        })
        .catch(() => {})
    }
    return Promise.resolve({ data: hit.value, fromCache: true, revalidating: !hit.fresh })
  }
  const gen = epoch
  return fetchOnce(key, fetcher).then((data) => {
    if (gen === epoch) writeCache(key, data, ttl)
    return { data, fromCache: false, revalidating: false }
  })
}

/** 强制刷新（下拉刷新用）：忽略缓存重新请求并写回 */
export function refreshFetch<T>(
  key: string,
  ttl: number,
  fetcher: Fetcher<T>
): Promise<T> {
  invalidate(key)
  return fetchOnce(key, fetcher).then((data) => {
    writeCache(key, data, ttl)
    return data
  })
}

// ---------------------------------------------------------------------------
// 统一的缓存键与 TTL（集中在此，避免各页各拍一个数字）
// ---------------------------------------------------------------------------
export const KEY = {
  me: 'me',
  progress: 'progress',
  tasks: 'tasks',
  pool: 'tasks/pool',
  adminProgress: 'admin/progress',
  packages: 'admin/packages',
  audios: 'admin/audios'
}

/** 角色信息极少变化，缓存久一点；登录 / 切身份时会主动失效 */
export const TTL_ME = 5 * 60 * 1000
/** 业务数据：短 TTL + 后台静默刷新，兼顾「秒开」与「数据新鲜」 */
export const TTL_DATA = 15 * 1000

/** 已登录后的通用失效：领取 / 上传 / 审核 / 导入 等写操作后调用 */
export function invalidateWorkData() {
  invalidate(KEY.progress)
  invalidate(KEY.tasks)
  invalidate(KEY.adminProgress)
  invalidate(KEY.audios)
}
