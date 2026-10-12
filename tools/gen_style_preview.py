# -*- coding: utf-8 -*-
"""
用「真实的 WXSS」生成一张可截图的 HTML 预览。

既有的 .workbuddy/preview/*.html 都是手写的 CSS 镜像，Chrome 会精确计算
calc(50% - 4px) 的小数宽度，所以预览里是两列、真机上却因为 rpx 取整退化成单列
—— 预览"骗"了我们。这个脚本直接把 asr-miniprogram 里的 app.wxss / 页面 wxss /
custom-tab-bar 转成 CSS（rpx -> px 按 375 设计宽度折算 0.5，page -> :root，
view -> div，text -> span），再用与 WXML 结构一致的标记渲染，最大化还原真机效果。

生成 5 个页面（见 PAGES）：
  style-preview.html         学习资源（采集端，含 tabBar 高亮块落点校验条）
  style-preview-audit.html   审计日志（管理端分包）
  style-preview-review.html  审核台（管理端分包）
  style-preview-import.html  导入任务（管理端分包）
  style-preview-login.html   登录（含品牌标尺寸体检条 1× / 1.5× / 2×）

用法: python tools/gen_style_preview.py
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

# 底部导航两套列表，必须与 asr-miniprogram/custom-tab-bar/index.js 保持一致。
# 项数按角色变（采集员 4 / 管理员 2），高亮块轨道宽 = 100/项数，是内联下发的，
# 所以这里渲染时也要把宽度带上（wxss 里已经没有 width 了）。
TABBAR_COLLECTOR = [
    ('首页', 'home', False),
    ('学习资源', 'resources', True),
    ('语言采集', 'record', False),
    ('我的', 'mine', False),
]

TABBAR_MANAGER = [
    ('任务管理', 'home', True),
    ('个人中心', 'mine', False),
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
    """学习资源页（采集员视角）底部那条 tabBar"""
    items = []
    for i, (txt, icon, on) in enumerate(TABBAR_COLLECTOR):
        items.append(
            '    <div class="item%s"><div class="ico-wrap"><img class="ico" src="%s" /></div>'
            '<div class="txt">%s</div></div>' % (' on' if on else '', icon_data(icon + ('-on' if on else '')), txt)
        )
    return '\n'.join(items)


def blob_idx():
    """采集员那套里当前选中项下标（高亮块 translateX = idx*100%，轨道宽 = 100/项数）"""
    for i, (_, _, on) in enumerate(TABBAR_COLLECTOR):
        if on:
            return i
    return 0


def tabbar_strip_html():
    """两套列表的**每个下标**各渲染一条 tabBar，验证 transform 版高亮块的落点。

    这里一律按「静止态」渲染（no-anim，即关掉 transition）——真机上切页时
    高亮块就是这个状态：新页面首个渲染帧就已经在正确位置，不播过渡。
    过渡只用于点击离场那一次，静态预览无法体现，故不在此模拟。

    轨道宽必须内联写出来：wxss 里的 .blob-track 已经不写 width 了，
    宽度是随列表长度下发的（custom-tab-bar/index.js 的 trackW）。
    """
    out = []
    for role, tabs in (('采集员（4 项）', TABBAR_COLLECTOR), ('管理员 / 审核员（2 项）', TABBAR_MANAGER)):
        out.append('  <div class="strip-title">%s</div>' % role)
        track_w = 100 // len(tabs)
        for i, (txt, _, _) in enumerate(tabs):
            items = []
            for j, (t, icon, _) in enumerate(tabs):
                on = j == i
                items.append(
                    '      <div class="item%s"><div class="ico-wrap"><img class="ico" src="%s" /></div>'
                    '<div class="txt">%s</div></div>' % (' on' if on else '', icon_data(icon + ('-on' if on else '')), t)
                )
            out.append(
                '  <div class="bar-demo">\n'
                '    <div class="bar">\n'
                '      <div class="blob-track no-anim" style="width: %d%%; transform: translateX(%d%%)"><div class="blob"></div></div>\n'
                '%s\n'
                '    </div>\n'
                '    <div class="bar-demo-label">blobIdx = %d → %s（静止态・no-anim，轨道宽 %d%%）</div>\n'
                '  </div>' % (track_w, i * 100, '\n'.join(items), i, txt, track_w)
            )
    return ('<div class="strip">\n'
            '  <div class="strip-title">底部导航高亮块落点校验（transform 版，逐个下标）</div>\n'
            + '\n'.join(out) + '\n'
            '</div>')


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

    <div class="footer">ASR 语音采集 · 录音规范与采集前自检</div>
  </div>
  <div class="bar">
    <div class="blob-track" style="transform: translateX(%(blob_x)d%%)"><div class="blob"></div></div>
%(tabbar)s
  </div>
</div>
""" % {'rules': rules_html(), 'texts': texts_html(), 'faq': faq_html(),
   'tabbar': tabbar_html(), 'blob_x': blob_idx() * 100}

def admin_shell(navtitle, inner):
    return """
<div class="viewport">
  <div class="statusbar"><span>18:32</span><span>▮▮▮</span></div>
  <div class="navtitle">%s</div>
  <div class="page">
%s
  </div>
</div>
""" % (navtitle, inner)


def audit_inner():
    cards = []
    rows = [
        ('审核通过', '10-11 21:03', 'u_admin_01', '管理员', 'recording', 'rec_2f81a9',
         '{"result":"approved","flags":[]}'),
        ('录领取任务', '10-11 20:58', 'u_col_07', '采集员', 'assignment', 'asg_5510ee', ''),
        ('导入任务包', '10-11 20:41', 'u_admin_01', '管理员', 'package', 'pkg_20261011', '共 240 条，split 下发'),
        ('审核退回', '10-11 19:22', 'u_rev_02', '审核员', 'recording', 'rec_77bb10',
         '{"reason":"环境嘈杂，底噪明显"}'),
    ]
    for action, time, op, role, tt, tid, detail in rows:
        detail_html = ('\n      <div class="detail">%s</div>' % detail) if detail else ''
        cards.append(
            '    <div class="card">\n'
            '      <div class="card-head"><span class="action">%s</span><span class="time">%s</span></div>\n'
            '      <div class="who"><span class="operator">%s</span><span class="role">%s</span></div>\n'
            '      <div class="target">对象 %s · %s</div>%s\n'
            '    </div>' % (action, time, op, role, tt, tid, detail_html)
        )
    return (
        '    <div class="topbar">\n'
        '      <div class="topbar-title">审计日志 · 共 128 条</div>\n'
        '      <button class="clean-btn">清理过期导出</button>\n'
        '    </div>\n'
        '<div class="tabs">'
        '<div class="tab on">全部</div><div class="tab">领取</div><div class="tab">上传</div>'
        '<div class="tab">审核</div><div class="tab">导入</div></div>\n'
        '    <div class="jobs-toggle">导出包留存 7 天 · 最近导出 2 个（点击展开）</div>\n'
        '    <div class="job">\n'
        '      <div class="job-line"><span class="job-id">job_8f3a21c4</span>'
        '<span class="job-status done">已完成</span></div>\n'
        '      <div class="job-meta"><span>240 条</span><span>10-11 20:14</span><span>到期 10-18</span></div>\n'
        '    </div>\n'
        '    <div class="job">\n'
        '      <div class="job-line"><span class="job-id">job_1c09bb77</span>'
        '<span class="job-status expired">已过期</span></div>\n'
        '      <div class="job-meta"><span>96 条</span><span>10-02 09:41</span>'
        '<span class="bad">音频文件缺失</span></div>\n'
        '    </div>\n' + '\n'.join(cards) + '\n    <div class="more">加载更多</div>'
    )


def review_inner():
    recs = [
        ('rec_2f81a9', 'uploaded', '待审核', ['音量偏低', '录音曾中断'], True),
        ('rec_5c31d0', 'approved', '已通过', [], False),
        ('rec_90ab42', 'rejected', '已退回', ['时长过短'], False),
    ]
    cards = []
    for rid, status, text, flags, show_actions in recs:
        flag_html = ''
        if flags:
            flag_html = ('\n      <div class="flags">'
                         + ''.join('<span class="flag">%s</span>' % f for f in flags)
                         + '</div>')
        if show_actions:
            actions = ('\n      <div class="actions"><button class="play-btn">试听</button>'
                       '<button class="ok-btn">通过</button>'
                       '<button class="no-btn">退回</button></div>')
        else:
            actions = '\n      <div class="actions"><button class="play-btn">试听</button>' \
                      '<span class="reviewed">已处理</span></div>'
        cards.append(
            '    <div class="card">\n'
            '      <div class="card-head"><span class="rid">%s</span>'
            '<span class="badge %s">%s</span></div>\n'
            '      <div class="meta"><span>采样率 16000Hz</span><span>声道 1</span>'
            '<span>编码 aac</span><span>时长 6.4s</span></div>%s%s\n'
            '    </div>' % (rid, status, text, flag_html, actions)
        )
    return (
        '    <div class="topbar">\n'
        '      <div class="tabs"><div class="tab on">待审核</div><div class="tab">已通过</div>'
        '<div class="tab">已退回</div><div class="tab">全部</div></div>\n'
        '      <button class="export-btn">导出</button>\n'
        '    </div>\n'
        '    <div class="count-tip">共 36 条，已显示 8 条</div>\n'
        + '\n'.join(cards) +
        '\n    <div class="more-row"><button class="more-btn">加载更多</button></div>'
    )


def import_inner():
    """导入任务页（paste 为主态）。

    真机上「粘贴文本 / 上传文件」是 wx:if 互斥、结果块也是 wx:if，
    这里为了**一次性看全所有组件样式**把它们都铺出来——本页只用于比对样式，
    不代表真实同屏内容。表单默认值取自 import.ts（formats=['aac','mp3'],
    sampleRate=16000, channels=1, DISTRIBUTE_LABELS[0]='每人一份（各录全部）'）。
    """
    users = [('u_col_07', True), ('u_col_12', True), ('u_col_23', False)]
    user_html = '\n'.join(
        '        <label class="user-item"><input type="checkbox"%s />'
        '<span class="user-name">%s</span></label>' % (' checked' if ck else '', uid)
        for uid, ck in users
    )
    return ''.join([
        '    <div class="tabs">\n'
        '      <div class="tab on">粘贴文本</div>\n'
        '      <div class="tab">上传文件</div>\n'
        '    </div>\n',

        '    <div class="form">\n'
        '      <div class="field"><span class="label">任务包 ID</span>'
        '<input class="input" placeholder="留空自动生成" /></div>\n'
        '      <div class="field"><span class="label">任务包名称</span>'
        '<input class="input" placeholder="留空用任务包 ID" /></div>\n'
        '      <div class="field-row">\n'
        '        <div class="field half"><span class="label">采样率</span>'
        '<input class="input" value="16000" /></div>\n'
        '        <div class="field half"><span class="label">声道</span>'
        '<input class="input" value="1" /></div>\n'
        '        <div class="field half"><span class="label">格式</span>'
        '<div class="input picker">aac</div></div>\n'
        '      </div>\n'
        '    </div>\n',

        '    <div class="card">\n'
        '      <div class="card-head"><span class="card-title">下发给</span>'
        '<div class="links"><span class="link">全选</span>'
        '<span class="link">清空</span></div></div>\n'
        '      <div class="hint">勾选后任务直接下发到该采集员的「我的任务」；'
        '不勾选则进入公共池，由采集员自行领取</div>\n'
        '      <div class="users">\n' + user_html + '\n      </div>\n'
        '      <div class="field distribute"><span class="label">分配方式</span>'
        '<div class="input picker">每人一份（各录全部）</div></div>\n'
        '    </div>\n',

        '    <div class="hint">每行一条待录制文本，空行自动忽略</div>\n'
        '    <div class="textarea">今天天气真好，我们一起去公园散步吧。<br />'
        '请朗读这一段新闻：本地气温将明显下降。</div>\n'
        '    <button class="submit">导入并下发</button>\n',

        '    <div class="hint">支持 Excel（.xlsx 两列：序号 / 汉语文本）与 CSV、JSON；'
        '「序号」列自动忽略</div>\n'
        '    <div class="file-picker">\n'
        '      <div class="file-name">任务文本_1012.xlsx</div>\n'
        '      <div class="file-tip">从聊天记录中选取（可先发到「文件传输助手」）</div>\n'
        '    </div>\n'
        '    <button class="submit">上传并下发</button>\n',

        '    <div class="result">\n'
        '      <div class="result-title">导入完成</div>\n'
        '      <div class="result-rows">\n'
        '        <span>任务包：pkg_20261012</span>\n'
        '        <span>新增文本：240</span>\n'
        '        <span>新增子任务：240</span>\n'
        '        <span>下发对象：u_col_07、u_col_12</span>\n'
        '        <span>分配方式：轮流分摊</span>\n'
        '        <span>跳过：3</span>\n'
        '      </div>\n'
        '      <div class="errs">\n'
        '        <span class="err">第 12 行：文本重复，已跳过</span>\n'
        '        <span class="err">第 88 行：空文本，已跳过</span>\n'
        '      </div>\n'
        '    </div>',
    ])


def logo_html():
    """品牌标的 DOM 结构，需与 pages/login/login.wxml 的 .logo 块保持一致。

    纯 CSS 绘制：U 形支架 / 话筒本体（内含 3 条网罩横缝）/ 支杆 / 底座，
    另有 .logo::before 做顶部柔光。改结构时两处要同步。
    """
    slits = ''.join('<div class="logo-slit"></div>' for _ in range(3))
    return ('<div class="logo">'
            '<div class="logo-yoke"></div>'
            '<div class="logo-body">' + slits + '</div>'
            '<div class="logo-neck"></div>'
            '<div class="logo-base"></div>'
            '</div>')


def login_inner():
    feats = [
        ('blue', '◉', '录音采集', '照文本逐句朗读并提交'),
        ('green', '✓', '审核与导出', '试听判定通过 / 退回，导出数据集'),
        ('violet', '＋', '任务导入', 'Excel 两列（序号 + 汉语文本）统一下发'),
    ]
    feat_html = '\n'.join(
        '      <div class="feat"><div class="feat-ico %s">%s</div>'
        '<div class="feat-body"><div class="feat-t">%s</div>'
        '<div class="feat-d">%s</div></div></div>' % f for f in feats
    )
    chips = ['首页', '学习资源', '语言采集', '我的']
    chip_html = ''.join(
        '<div class="tab-chip%s">%s</div>' % (' active' if c == '语言采集' else '', c)
        for c in chips
    )
    return ''.join([
        '    <div class="bg-blob bg1"></div>\n',
        '    <div class="bg-blob bg2"></div>\n',
        '    <div class="bg-blob bg3"></div>\n',
        '    <div class="brand">\n      ' + logo_html() + '\n'
        '      <div class="title">ASR 语音采集</div>\n    </div>\n',
        '    <div class="tabs">' + chip_html + '</div>\n',
        '    <div class="card">\n' + feat_html + '\n    </div>\n',
        '    <button class="login-btn">微信登录（采集员）</button>\n',
        '    <button class="admin-btn">管理员登录（演示）</button>',
    ])


def logo_strip_html():
    """品牌标尺寸体检：1× 是登录页实际尺寸，1.5×/2× 用来看细节是否站得住。

    用 transform: scale() 整体缩放，而不是改 width/height —— 标内部的几何是
    按 136rpx 手工对位的固定值，改外框会让各部件错位。
    """
    out = []
    for scale, label in ((1, '1× · 136rpx（登录页实际尺寸）'),
                         (1.5, '1.5×'), (2, '2× · 放大看细节')):
        out.append(
            '  <div class="zoom-item">\n'
            '    <div class="zoom-stage"><div class="zoom-box" style="transform: scale(%s)">%s</div></div>\n'
            '    <div class="zoom-label">%s</div>\n'
            '  </div>' % (scale, logo_html(), label)
        )
    return ('<div class="strip">\n'
            '  <div class="strip-title">品牌标尺寸体检（纯 CSS 绘制 · 零位图）</div>\n'
            '  <div class="zoom-row">\n' + '\n'.join(out) + '\n  </div>\n'
            '</div>')


DOC = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>真实样式预览 · %(title)s</title>
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
/* ===== 高亮块落点校验条 ===== */
.strip { width: 375px; padding: 18px 0 30px; }
.strip-title { font: 600 14px/1.6 -apple-system, "PingFang SC", sans-serif; color: #12171f; margin: 0 0 12px; }
.bar-demo { position: relative; width: 375px; height: 73px; margin-bottom: 26px; border-radius: 10px; overflow: hidden; }
.bar-demo-label { position: absolute; top: -22px; left: 0; font: 12px/1.6 -apple-system, "PingFang SC", sans-serif; color: #5a6470; }
/* ===== 品牌标尺寸体检条 ===== */
.zoom-row { display: flex; align-items: flex-start; }
.zoom-item { display: flex; flex-direction: column; margin-right: 54px; }
.zoom-stage { width: 152px; height: 162px; display: flex; align-items: center; justify-content: center; }
.zoom-box { width: 68px; height: 68px; }
.zoom-label { margin-top: 6px; text-align: center; font: 12px/1.6 -apple-system, "PingFang SC", sans-serif; color: #5a6470; }
</style>
</head>
<body>
%(body)s
%(strip)s
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


PAGES = [
    # (输出文件名, 预览标题, 参与转换的 WXSS, body, 页面下方的体检条 HTML)
    ('style-preview.html', '学习资源',
     ['app.wxss', 'pages/resources/resources.wxss', 'custom-tab-bar/index.wxss'],
     BODY_RESOURCES, tabbar_strip_html()),
    ('style-preview-audit.html', '审计日志（管理端分包）',
     ['app.wxss', 'subpackages/admin/audit/audit.wxss'],
     admin_shell('审计日志', audit_inner()), ''),
    ('style-preview-review.html', '审核台（管理端分包）',
     ['app.wxss', 'subpackages/admin/review/review.wxss'],
     admin_shell('审核台', review_inner()), ''),
    ('style-preview-import.html', '导入任务（管理端分包）',
     ['app.wxss', 'subpackages/admin/import/import.wxss'],
     admin_shell('导入任务', import_inner()), ''),
    ('style-preview-login.html', '登录',
     ['app.wxss', 'pages/login/login.wxss'],
     admin_shell('登录', login_inner()), logo_strip_html()),
]


def main():
    outdir = os.path.join(ROOT, '.workbuddy', 'preview')
    for name, title, css_files, body, strip in PAGES:
        css = read_css(*css_files)
        html = DOC % {
            'css': css,
            'body': body,
            'title': title,
            'strip': strip,
        }
        path = os.path.join(outdir, name)
        with io.open(path, 'w', encoding='utf-8') as f:
            f.write(html)
        print('written', os.path.relpath(path, ROOT), len(html), 'bytes')


if __name__ == '__main__':
    main()
