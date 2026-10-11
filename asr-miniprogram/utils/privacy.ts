// 微信平台隐私授权封装。
// 依据微信规范：调用录音等涉及用户隐私的接口前，需先获得平台级隐私授权，
// 且已在小程序后台发布《用户隐私保护指引》。
// 相关 API：wx.getPrivacySetting / wx.requirePrivacyAuthorize / wx.openPrivacyContract
// 具体规则与最低基础库版本以微信官方最新文档为准。

export interface PrivacySetting {
  needAuthorization: boolean
  privacyContractName: string
}

const DEFAULT_CONTRACT = '《用户隐私保护指引》'

// 查询当前是否需要弹隐私授权，以及隐私协议名称
export function getPrivacySetting(): Promise<PrivacySetting> {
  return new Promise((resolve) => {
    const w = wx as any
    if (!w.getPrivacySetting) {
      resolve({ needAuthorization: false, privacyContractName: DEFAULT_CONTRACT })
      return
    }
    w.getPrivacySetting({
      success: (res: any) =>
        resolve({
          needAuthorization: !!res.needAuthorization,
          privacyContractName: res.privacyContractName || DEFAULT_CONTRACT
        }),
      fail: () => resolve({ needAuthorization: false, privacyContractName: DEFAULT_CONTRACT })
    })
  })
}

// 调用录音等隐私接口前确保已获平台隐私授权。
// 返回 true=可继续；false=用户拒绝或未配置导致不能继续。
export function ensurePrivacyAuthorize(): Promise<boolean> {
  return new Promise((resolve) => {
    const w = wx as any
    // 低版本基础库无此 API：放行（生产建议要求基础库 ≥ 2.32.3）
    if (!w.requirePrivacyAuthorize) {
      resolve(true)
      return
    }
    w.requirePrivacyAuthorize({
      success: () => resolve(true),
      fail: () => resolve(false)
    })
  })
}

// 打开平台《用户隐私保护指引》页面
export function openPrivacyContract(): Promise<boolean> {
  return new Promise((resolve) => {
    const w = wx as any
    if (!w.openPrivacyContract) {
      resolve(false)
      return
    }
    w.openPrivacyContract({
      success: () => resolve(true),
      fail: () => resolve(false)
    })
  })
}
