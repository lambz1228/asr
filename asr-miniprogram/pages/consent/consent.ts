import { submitConsent, withdrawConsent, getConsentStatus } from '../../utils/consent'
import { logout } from '../../utils/auth'
import { openPrivacyContract, getPrivacySetting } from '../../utils/privacy'
import { TAB } from '../../utils/nav'

Page({
  data: {
    agreed: false,
    submitting: false,
    signed: false, // 后端当前是否已签署生效中的同意
    withdrawing: false,
    privacyContractName: '《用户隐私保护指引》'
  },
  async onLoad() {
    try {
      const st = await getConsentStatus()
      this.setData({ signed: st.signed })
    } catch {
      this.setData({ signed: false })
    }
    // 读取平台隐私协议名称，供链接展示
    try {
      const ps = await getPrivacySetting()
      this.setData({ privacyContractName: ps.privacyContractName || '《用户隐私保护指引》' })
    } catch {
      /* 忽略：开发态未配置隐私协议属正常 */
    }
  },
  onOpenPrivacy() {
    openPrivacyContract().then((okFlag) => {
      if (!okFlag) {
        wx.showToast({ title: '暂无法打开（需后台配置隐私协议）', icon: 'none' })
      }
    })
  },
  onAgreeChange(e: any) {
    this.setData({ agreed: (e.detail.value || []).length > 0 })
  },
  async onSubmitConsent() {
    if (!this.data.agreed) {
      wx.showToast({ title: '请先勾选「我已阅读并同意」', icon: 'none' })
      return
    }
    this.setData({ submitting: true })
    try {
      await submitConsent('1.0')
      wx.setStorageSync('consentSigned', true)
      wx.showToast({ title: '已签署同意', icon: 'success' })
      setTimeout(() => wx.switchTab({ url: TAB.home }), 600)
    } catch (e: any) {
      wx.showToast({ title: '提交失败: ' + (e.message || ''), icon: 'none' })
    } finally {
      this.setData({ submitting: false })
    }
  },
  onWithdraw() {
    wx.showModal({
      title: '撤回同意',
      content: '撤回后您将无法继续上传音频；已上传数据将按保留期与撤回处理规则留存。确定撤回吗？',
      confirmText: '确定撤回',
      confirmColor: '#e64340',
      success: async (r) => {
        if (!r.confirm) return
        this.setData({ withdrawing: true })
        try {
          const res = await withdrawConsent()
          if (res.withdrawn) {
            wx.removeStorageSync('consentSigned')
            this.setData({ signed: false, agreed: false })
            wx.showToast({ title: '已撤回同意', icon: 'none' })
          } else {
            wx.showToast({ title: res.message || '无生效中的同意', icon: 'none' })
          }
        } catch (e: any) {
          wx.showToast({ title: '撤回失败: ' + (e.message || ''), icon: 'none' })
        } finally {
          this.setData({ withdrawing: false })
        }
      }
    })
  },
  onExit() {
    // 未授权则退出登录回到登录页（PIPL：不得强制同意）
    wx.showModal({
      title: '暂不授权',
      content: '未签署语音信息同意书将无法上传音频。确定退出吗？',
      confirmText: '退出',
      confirmColor: '#e64340',
      success: (r) => {
        if (!r.confirm) return
        logout()
        wx.removeStorageSync('consentSigned')
        wx.reLaunch({ url: '/pages/login/login' })
      }
    })
  }
})
