/**
 * ASR 语音采集小程序 — 项目介绍视频文案
 *
 * 结构固定为：intro（开场）→ pain（痛点）→ feature（核心功能）→ usage（使用方式）→ cta（行动号召）
 * 配色沿用小程序品牌蓝 #1a8cff，深蓝底 + 青色高光。
 * 渲染：node <skill>/scripts/render-video.js --config ./config.js --out ./out/asr-intro.mp4
 */
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) module.exports = factory();
  else root.PIV_CONFIG = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  return {
    video: { width: 1920, height: 1080, fps: 30 },

    meta: {
      projectName: 'ASR 语音采集小程序',
      tagline: '采集 · 审核 · 导出，一条流水线跑通',
      cornerTag: '语音数据集生产平台',
      colors: {
        bgTop: '#08111F',
        bgBottom: '#0E1B33',
        accent: '#3BA9FF',
        accent2: '#1A8CFF',
        text: '#F8FAFC',
        sub: '#94A3B8',
        danger: '#F87171',
        ok: '#34D399',
        cardBg: 'rgba(14, 27, 51, 0.82)',
        cardLine: 'rgba(148, 163, 184, 0.28)'
      }
    },

    scenes: [
      {
        id: 'intro',
        layout: 'intro',
        kicker: 'PROJECT INTRO',
        title: '语音数据采集',
        subtitle: '让数据集生产，从三周缩短到三天',
        fallbackDuration: 6
      },
      {
        id: 'pain',
        layout: 'pain',
        kicker: '痛点',
        title: '语音采集，卡在哪里',
        subtitle: '散、慢、乱 —— 数据质量全靠人盯',
        fallbackDuration: 14,
        items: [
          { icon: 'folders', title: '任务难分发', desc: '文本散落在表格和聊天记录里，逐人派发耗时又容易漏' },
          { icon: 'warn', title: '质量难保证', desc: '环境噪声、中途打断没人察觉，交上来才发现要返工' },
          { icon: 'clock', title: '进度不透明', desc: '谁录了多少、还差多少，只能反复追问、手工统计' }
        ]
      },
      {
        id: 'feature',
        layout: 'feature',
        kicker: '核心功能',
        title: '三大核心能力',
        subtitle: '从下发到入库，全流程线上闭环',
        fallbackDuration: 14,
        items: [
          { icon: 'bolt', title: '一键导入下发', desc: '上传 Excel，按人拆成子任务，采集员登录即见' },
          { icon: 'link', title: '队列式录音', desc: '照文本逐条录制，支持暂停、中断标记与重录' },
          { icon: 'chart', title: '审核与导出', desc: '在线试听通过或退回，一键导出音频与标注清单' }
        ]
      },
      {
        id: 'usage',
        layout: 'usage',
        kicker: '使用方式',
        title: '三步跑通全流程',
        subtitle: '管理员建任务，采集员录语音，审核员把质量',
        fallbackDuration: 12,
        steps: [
          { title: '导入任务', desc: 'Excel 两列：序号 + 汉语文本' },
          { title: '录音采集', desc: '照文本录制，可暂停、可重录' },
          { title: '审核导出', desc: '试听通过，导出标准数据集' }
        ]
      },
      {
        id: 'cta',
        layout: 'cta',
        kicker: 'GET STARTED',
        title: '开始采集',
        subtitle: '把语音数据集生产，交给一套系统',
        ctaLine: '微信搜索小程序 · 登录即可开始',
        fallbackDuration: 8
      }
    ],

    voiceover: { enabled: false, audioDir: 'audio' }
  };
});
