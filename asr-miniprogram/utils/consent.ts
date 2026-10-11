// 同意书相关接口：查询生效状态、提交单独同意、撤回同意。
// 对应后端 app/routers/auth.py：/auth/consent/status、/auth/consent、/auth/consent/withdraw
// 语音属《个人信息保护法》敏感个人信息，需单独、明确的同意，且可随时撤回。
import { request } from './request'

export interface ConsentStatus {
  signed: boolean
  type: string
  version?: string
  signedAt?: string
}

export async function getConsentStatus(): Promise<ConsentStatus> {
  return request<ConsentStatus>({ url: '/auth/consent/status', method: 'GET' })
}

export async function submitConsent(version = '1.0'): Promise<{ signed: boolean; type: string }> {
  return request({ url: '/auth/consent', method: 'POST', data: { version, type: 'voice_sensitive' } })
}

export async function withdrawConsent(type = 'voice_sensitive'): Promise<{ withdrawn: boolean; type: string }> {
  return request({ url: '/auth/consent/withdraw', method: 'POST', data: { type } })
}
