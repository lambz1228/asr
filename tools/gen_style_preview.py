# -*- coding: utf-8 -*-
"""
用「真实的 WXSS」生成一张可截图的 HTML 预览。

为什么要这个：之前 .workbuddy/preview/unified-nav.html 是手写的 CSS 镜像，
Chrome 会精确计算 calc(50% - 4px) 的小数宽度，所以预览里是两列、
真机上却因为 rpx 取整退化成单列 —— 预览"骗"了我们。
这个脚本直接把 asr-miniprogram 里的 app.wxss / 页面 wxss / custom-tab-bar 转成 CSS
（rpx -> px 按 375 设计宽度折算 0.5，page -> :root，view -> div，text -> span），
再用与 WXML 结构一致的标记渲染，最大化还原真机效果。

用法: python tools/gen_style_preview.py [page]    # page: resources | home
"""
import base64
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MP = os.path.join(ROOT, 'asr-miniprogram')
OUT = os.path.join(ROOT, '.workbuddy', 'preview', 'style-preview.html')

# 与 resources.ts / home.ts 中的演示数据保持一致
RULES = [
    ('🤫', '环境安静', '关闭风扇 / 空调强风档，避免街噪与他人说话声'),
    ('📏', '距离稳定', '嘴距麦克风 10–15cm，全程保持一致，不要忽远忽近'),
    ('🐢', '语速平稳', '按自然语速朗读，约 200 字/分钟，句间稍作停顿'),
    ('🚫', '不读错不回读', '读错请停止并整句重录，不要中途纠正或重读某个字'),
    ('🗣', '口语化自然', '用普通话朗读，不加入方言、口头禅或拖长音'),
    ('⏱', '单句时长', '单条控制在 2–15 秒，太长可放慢但不要停顿过久'),
]

FAQ = [
    ('音频太轻 / 有明显底噪', '多因距离过远或环境嘈杂。请靠近麦克风 10–15cm，换到安静房间重录。'),
    ('读错字、漏字、自行加字', '必须与文本逐字一致。读错即刻停止，点「清除重录」整句重新录制。'),
    ('录音被打断（来电 / 切后台）', '微信录音在后台不可靠，被打断的内容可能不完整。请回到本页重新录制。'),
]

TEXTS = [
    ('今天天气很好，我们一起去公园散步。', 'claimed'),
    ('请把窗户关上，外面风有点大。', 'rejected'),
    ('这个问题我们明天开会再讨论。', 'approved'),
]
STATUS_TEXT = {'claimed': '待录制', 'rejected': '已退回', 'approved': '已通过'}

TABBAR = [
    ('首页', 'home', False),
    ('学习资源', 'resources', True),
    ('语言采集', 'record', False),
    ('我的', 'mine', False),
]


def rpx_to_px(css):
    """rpx -> px（375 设计宽度下 1rpx = 0.5px），env() 用 iPhone 安全区兜底"""
    def sub(m):
        v = float(m.group(1)) * 0.5
        s = ('%.3f' % v).rstrip('0').rstrip('.')
        return (s or '0') + 'px'
    css = re.sub(r'(-?\d*\.?\d+)rpx', sub, css)
    css = css.replace('env(safe-area-inset-bottom)', '34px')
    return css


ELEM_MAP = [('view', 'div'), ('text', 'span'), ('image', 'img'), ('page', ':root')]


def convert_selectors(css, ):
    """只把「选择器部分」里的 view/text/image/page 换成 HTML 标签"""
    out = []
    i = 0
    while i < len(css):
        j = css.find('{', i)
        if j < 0:
            out.append(css[i:])
            break
        sel = css[i:j]
        # @keyframes / @media 之类的 at-rule 不动
        if '@' not in sel:
            for a, b in ELEM_MAP:
                sel = re.sub(r'(?<![\w.\-#])%s(?![\w-])' % a, b, sel)
        out.append(sel + '{')
        i = j + 1
    return ''.join(out)


def read_css(*rel_paths):
    parts = []
    for rel in rel_paths:
        with io.open(os.path.join(MP, rel), encoding='utf-8') as f:
            parts.append(convert_selectors(rpx_to_px(f.read())))
    return '\n'.join(parts)


def icon_data(name):
    with open(os.path.join(MP, 'images', 'tabbar', name + '.png'), 'rb') as f:
        return 'data:image/png;base64,' + base64.b64encode(f.read()).decode()


def rules_html():
    return '\n'.join(
        '      <div class="rule"><div class="rule-ico">%s</div>'
        '<div class="rule-title">%s</div><div class="rule-desc">%s</div></div>' % r for r in RULES
    )


def texts_html():
    return '\n'.join(
        '      <div class="card text-item"><div class="text-line">%s</div>'
        '<span class="status %s">%s</span></div>' % (t, s, STATUS_TEXT[s]) for t, s in TEXTS
    )


def faq_html():
    return '\n'.join(
        '      <div class="faq"><div class="faq-q"><span class="faq-mark">+</span>'
        '<span class="faq-q-text">%s</span></div></div>' % q for q, _ in FAQ
    )


def tabbar_html():
    items = []
    for i, (txt, icon, on) in enumerate(TABBAR):
        items.append(
            '    <div class="item%s"><div class="ico-wrap"><img class="ico" src="%s" /></div>'
            '<div class="txt">%s</div></div>' % (' on' if on else '', icon_data(icon + ('-on' if on else '')), txt)
        )
    return '\n'.join(items)


def blob_pos():
    for i, (_, _, on) in enumerate(TABBAR):
        if on:
            return str(i * 25 + 12.5)
    return '12.5'


BODY_RESOURCES = """
<div class="viewport">
  <div class="statusbar"><span>18:32</span><span>▮▮▮</span></div>
  <div class="navtitle">学习资源</div>
  <div class="page stagger">
    <div class="hero">
      <div class="hero-blob hero-blob1"></div>
      <div class="hero-blob hero-blob2"></div>
      <div class="hero-row">
        <div class="hero-main">
          <div class="hero-hi">学习资源</div>
          <div class="hero-sub"><span class="role-tag">采集员</span><span class="hero-hint">录音规范 · 朗读素材</span></div>
        </div>
        <div class="hero-emoji">📖</div>
      </div>
    </div>

    <div class="sec-head"><div class="sec-title"><div class="sec-bar"></div><span>录音规范</span></div></div>
    <div class="rules">
%(rules)s
    </div>

    <div class="sec-head"><div class="sec-title"><div class="sec-bar green"></div><span>采集前自检</span></div></div>
    <div class="list">
      <div class="row"><span class="dot ok">✓</span><div class="row-body"><div class="row-title">《语音信息同意书》</div><div class="row-desc">已签署，可正常上传</div></div><span class="row-arrow">›</span></div>
      <div class="row"><span class="dot info">?</span><div class="row-body"><div class="row-title">微信《用户隐私保护指引》</div><div class="row-desc">录音前需通过微信平台隐私授权，点击查看协议</div></div><span class="row-arrow">›</span></div>
    </div>

    <div class="sec-head">
      <div class="sec-title"><div class="sec-bar violet"></div><span>我的文本库</span></div>
      <span class="sec-more">3/3 条</span>
    </div>
    <div class="search"><span class="search-ico">🔍</span><input class="search-input" placeholder="搜索文本内容，点条目直接去录" /></div>
%(texts)s

    <div class="sec-head"><div class="sec-title"><div class="sec-bar amber"></div><span>常见退回原因</span></div></div>
    <div class="list">
%(faq)s
    </div>

    <div class="footer">ASR 语音采集 · 两个身份共用同一套导航与规范</div>
  </div>
  <div class="bar">
    <div class="blob" style="left:%%(blob_pos)s%%"></div>
%(tabbar)s
  </div>
</div>
""" % {'rules': rules_html(), 'texts': texts_html(), 'faq': faq_html(),
   'tabbar': tabbar_html(), 'blob_pos': blob_pos()}

DOC = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>真实样式预览 · 学习资源</title>
<style>
/* ===== 以下 CSS 由 asr-miniprogram 的真实 WXSS 转换而来（rpx -> px, view -> div ...） ===== */
%(css)s
/* ===== 仅用于预览的外壳 ===== */
html, body { margin: 0; padding: 0; background: #dfe4ec; }
.viewport {
  position: relative;
  width: 375px;
  height: 812px;
  background: var(--bg);
  overflow: hidden;
  box-shadow: 0 10px 40px rgba(20,33,56,.25);
}
/* tabBar 在真机上是 fixed；预览里限定在手机框内 */
.bar {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
}
.statusbar {
  height: 44px; display: flex; align-items: center; justify-content: space-between;
  padding: 0 18px; font-size: 13px; font-weight: 600; color: #12171f; background: #fff;
}
.navtitle {
  height: 44px; line-height: 44px; text-align: center; font-size: 16px; font-weight: 600;
  color: #12171f; background: #fff; border-bottom: 1px solid rgba(20,33,56,.06);
}
.page {
  position: absolute; left: 0; right: 0; top: 88px; bottom: 0;
  overflow-y: auto; min-height: 0;
}
/* 滚动条隐藏一点，视觉更接近真机 */
.page::-webkit-scrollbar { width: 0; }
/* HTML 的 input 默认带边框，小程序里没有，去掉以还原真机观感 */
input { border: none; outline: none; background: transparent; }
.tipbar { font: 12px/1.6 -apple-system, "PingFang SC", sans-serif; color: #5a6470; }
</style>
</head>
<body>
%(body)s
<script>
// 支持 file:///...style-preview.html#bottom 直接滚到底，用来检查底部留白
if (location.hash.indexOf('bottom') >= 0) {
  var pg = document.querySelector('.page');
  if (pg) pg.scrollTop = pg.scrollHeight;
}
</script>
</body>
</html>
"""


def main():
    css = read_css('app.wxss', 'pages/resources/resources.wxss', 'custom-tab-bar/index.wxss')
    html = DOC % {'css': css, 'body': BODY_RESOURCES}
    with io.open(OUT, 'w', encoding='utf-8') as f:
        f.write(html)
    print('written', os.path.relpath(OUT, ROOT), len(html), 'bytes')


if __name__ == '__main__':
    main()
