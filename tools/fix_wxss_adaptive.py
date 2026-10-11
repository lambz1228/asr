# -*- coding: utf-8 -*-
"""
WXSS 自适应修复（一次性脚本，可重复运行：已修复的会跳过）

修两类在小程序里会「不生效 / 退化成单列」的写法：
  1) width: calc(50% - 8rpx) —— 百分比与 rpx 混用，取整误差会让
     (50% - 8rpx) * 2 + gap(16rpx) 刚好超过 100%，于是每行只放得下一张卡。
     改成纯百分比 + justify-content: space-between。
  2) flex 容器 gap —— 老基础库 / iOS 13 及更早的系统不支持 flex gap，
     列间距会整体消失。统一改成兄弟元素的 margin。

以及：页面底部 padding 用 calc(rpx + env()) 时补一条不依赖 env() 的兜底声明。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MP = os.path.join(ROOT, 'asr-miniprogram')

# (文件, [ (old, new), ... ])
PLAN = [
    ('app.wxss', [
        (
            "  /* 自定义 tabBar 高度（页面底部留白的唯一来源） */\n  --tabbar-h: 152rpx;\n",
            "  /* 自定义 tabBar 尺寸（页面底部留白的唯一来源，见 .tab-pad） */\n"
            "  --tabbar-h: 108rpx;\n"
            "  --tab-pad: 190rpx;\n",
        ),
        (
            "/* tab 页底部留白：避开自定义 tabBar 与全面屏安全区 */\n"
            ".tab-pad {\n"
            "  padding-bottom: calc(var(--tabbar-h) + env(safe-area-inset-bottom));\n"
            "}\n",
            "/* tab 页底部留白：避开自定义 tabBar 与全面屏安全区\n"
            "   注意：calc() 里混用 % 与 rpx 在部分机型 / 基础库上会被整条丢掉，\n"
            "   甚至让 flex 换行计算失真，所以这里只混用同为长度的 rpx 与 env()，\n"
            "   并保留一条不依赖 env() 的兜底声明。 */\n"
            ".tab-pad {\n"
            "  padding-bottom: var(--tab-pad);\n"
            "  padding-bottom: calc(var(--tab-pad) + env(safe-area-inset-bottom));\n"
            "}\n",
        ),
    ]),

    ('pages/resources/resources.wxss', [
        (
            ".page {\n  min-height: 100vh;\n  box-sizing: border-box;\n"
            "  padding: 24rpx 24rpx calc(190rpx + env(safe-area-inset-bottom));\n}\n",
            ".page {\n  min-height: 100vh;\n  box-sizing: border-box;\n"
            "  /* 拆成三条写：最后一条 calc 若被机型丢弃，仍保留固定底部留白 */\n"
            "  padding: 24rpx 24rpx 0;\n"
            "  padding-bottom: var(--tab-pad);\n"
            "  padding-bottom: calc(var(--tab-pad) + env(safe-area-inset-bottom));\n}\n",
        ),
        (
            ".rules {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 16rpx;\n}\n"
            ".rule {\n  width: calc(50% - 8rpx);\n  box-sizing: border-box;\n",
            ".rules {\n  display: flex;\n  flex-wrap: wrap;\n"
            "  /* 不用 gap：老基础库 / iOS 13- 不支持 flex gap */\n"
            "  justify-content: space-between;\n}\n"
            ".rule {\n"
            "  /* 纯百分比，不用 calc(50% - 8rpx)：% 与 rpx 混算的取整误差会让\n"
            "     两列加间距刚好超过 100%，每行只放得下一张卡，退化成单列 */\n"
            "  width: 48.6%;\n"
            "  margin-bottom: 18rpx;\n  box-sizing: border-box;\n",
        ),
        (
            ".sk-wrap {\n  display: flex;\n  flex-direction: column;\n  gap: 16rpx;\n}\n",
            ".sk-wrap {\n  display: flex;\n  flex-direction: column;\n}\n"
            ".sk-wrap > view + view {\n  margin-top: 16rpx;\n}\n",
        ),
    ]),

    ('pages/home/home.wxss', [
        (
            ".page {\n  min-height: 100vh;\n  box-sizing: border-box;\n"
            "  padding: 24rpx 24rpx calc(190rpx + env(safe-area-inset-bottom));\n}\n",
            ".page {\n  min-height: 100vh;\n  box-sizing: border-box;\n"
            "  /* 拆成三条写：最后一条 calc 若被机型丢弃，仍保留固定底部留白 */\n"
            "  padding: 24rpx 24rpx 0;\n"
            "  padding-bottom: var(--tab-pad);\n"
            "  padding-bottom: calc(var(--tab-pad) + env(safe-area-inset-bottom));\n}\n",
        ),
        (
            ".chips {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 12rpx;\n  margin-top: 16rpx;\n}\n"
            ".chip {\n  font-size: 21rpx;\n  color: var(--t2);\n  background: #f4f6fa;\n"
            "  padding: 5rpx 14rpx;\n  border-radius: 8rpx;\n}\n",
            ".chips {\n  display: flex;\n  flex-wrap: wrap;\n  margin-top: 16rpx;\n}\n"
            ".chip {\n  font-size: 21rpx;\n  color: var(--t2);\n  background: #f4f6fa;\n"
            "  padding: 5rpx 14rpx;\n  border-radius: 8rpx;\n  margin: 0 12rpx 12rpx 0;\n}\n",
        ),
        (
            "  display: flex;\n  flex-direction: column;\n  gap: 6rpx;\n"
            "  animation: slideDown 0.28s cubic-bezier(0.22, 0.9, 0.32, 1) backwards;\n",
            "  display: flex;\n  flex-direction: column;\n"
            "  animation: slideDown 0.28s cubic-bezier(0.22, 0.9, 0.32, 1) backwards;\n",
        ),
        (
            ".reject-title {\n  font-size: 21rpx;\n  color: var(--red);\n  font-weight: 600;\n}\n",
            ".reject-title {\n  font-size: 21rpx;\n  color: var(--red);\n  font-weight: 600;\n"
            "  margin-bottom: 6rpx;\n}\n",
        ),
        (
            ".stats {\n  display: flex;\n  gap: 16rpx;\n  margin-bottom: 22rpx;\n}\n",
            ".stats {\n  display: flex;\n  margin-bottom: 22rpx;\n}\n"
            ".stat + .stat {\n  margin-left: 16rpx;\n}\n",
        ),
        (
            ".entries {\n  display: flex;\n  flex-direction: column;\n  gap: 16rpx;\n  margin-bottom: 28rpx;\n}\n",
            ".entries {\n  display: flex;\n  flex-direction: column;\n  margin-bottom: 28rpx;\n}\n"
            ".entries > view + view {\n  margin-top: 16rpx;\n}\n",
        ),
        (
            ".sk-wrap {\n  display: flex;\n  flex-direction: column;\n  gap: 16rpx;\n}\n",
            ".sk-wrap {\n  display: flex;\n  flex-direction: column;\n}\n"
            ".sk-wrap > view + view {\n  margin-top: 16rpx;\n}\n",
        ),
    ]),

    ('pages/profile/profile.wxss', [
        (
            ".page {\n  min-height: 100vh;\n  box-sizing: border-box;\n"
            "  padding: 24rpx 24rpx calc(190rpx + env(safe-area-inset-bottom));\n}\n",
            ".page {\n  min-height: 100vh;\n  box-sizing: border-box;\n"
            "  /* 拆成三条写：最后一条 calc 若被机型丢弃，仍保留固定底部留白 */\n"
            "  padding: 24rpx 24rpx 0;\n"
            "  padding-bottom: var(--tab-pad);\n"
            "  padding-bottom: calc(var(--tab-pad) + env(safe-area-inset-bottom));\n}\n",
        ),
        (
            ".chips {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 12rpx;\n  margin-top: 16rpx;\n}\n"
            ".chip {\n  font-size: 21rpx;\n  color: var(--t2);\n  background: #f4f6fa;\n"
            "  padding: 5rpx 14rpx;\n  border-radius: 8rpx;\n}\n",
            ".chips {\n  display: flex;\n  flex-wrap: wrap;\n  margin-top: 16rpx;\n}\n"
            ".chip {\n  font-size: 21rpx;\n  color: var(--t2);\n  background: #f4f6fa;\n"
            "  padding: 5rpx 14rpx;\n  border-radius: 8rpx;\n  margin: 0 12rpx 12rpx 0;\n}\n",
        ),
    ]),

    ('pages/record/record.wxss', [
        (
            ".page {\n  min-height: 100vh;\n  box-sizing: border-box;\n"
            "  padding: 24rpx 26rpx calc(190rpx + env(safe-area-inset-bottom));\n}\n",
            ".page {\n  min-height: 100vh;\n  box-sizing: border-box;\n"
            "  /* 拆成三条写：最后一条 calc 若被机型丢弃，仍保留固定底部留白 */\n"
            "  padding: 24rpx 26rpx 0;\n"
            "  padding-bottom: var(--tab-pad);\n"
            "  padding-bottom: calc(var(--tab-pad) + env(safe-area-inset-bottom));\n}\n",
        ),
        (
            ".wave {\n  display: flex;\n  align-items: center;\n  justify-content: center;\n"
            "  gap: 10rpx;\n  height: 44rpx;\n}\n",
            ".wave {\n  display: flex;\n  align-items: center;\n  justify-content: center;\n"
            "  height: 44rpx;\n}\n"
            ".wv + .wv {\n  margin-left: 10rpx;\n}\n",
        ),
        (
            ".sk-wrap {\n  display: flex;\n  flex-direction: column;\n  gap: 18rpx;\n}\n",
            ".sk-wrap {\n  display: flex;\n  flex-direction: column;\n}\n"
            ".sk-wrap > view + view {\n  margin-top: 18rpx;\n}\n",
        ),
    ]),

    ('pages/login/login.wxss', [
        (
            ".tabs {\n  display: flex;\n  justify-content: center;\n  gap: 12rpx;\n"
            "  margin: 32rpx 0 26rpx;\n"
            "  animation: riseIn 0.5s cubic-bezier(0.22, 0.9, 0.32, 1) 0.08s backwards;\n}\n",
            ".tabs {\n  display: flex;\n  justify-content: center;\n"
            "  margin: 32rpx 0 26rpx;\n"
            "  animation: riseIn 0.5s cubic-bezier(0.22, 0.9, 0.32, 1) 0.08s backwards;\n}\n"
            ".tab-chip + .tab-chip {\n  margin-left: 12rpx;\n}\n",
        ),
    ]),

    ('pages/consent/consent.wxss', [
        (
            "  padding: 24rpx 28rpx calc(300rpx + env(safe-area-inset-bottom));\n",
            "  padding: 24rpx 28rpx 300rpx;\n"
            "  padding-bottom: calc(300rpx + env(safe-area-inset-bottom));\n",
        ),
        (
            "  padding: 24rpx 28rpx calc(24rpx + env(safe-area-inset-bottom));\n",
            "  padding: 24rpx 28rpx 24rpx;\n"
            "  padding-bottom: calc(24rpx + env(safe-area-inset-bottom));\n",
        ),
        (
            ".btn-row {\n  display: flex;\n  gap: 20rpx;\n  margin-top: 16rpx;\n}\n",
            ".btn-row {\n  display: flex;\n  margin-top: 16rpx;\n}\n"
            ".btn-row > button + button {\n  margin-left: 20rpx;\n}\n",
        ),
    ]),

    ('subpackages/admin/review/review.wxss', [
        (
            ".topbar {\n  display: flex;\n  align-items: center;\n  gap: 16rpx;\n"
            "  margin-bottom: 16rpx;\n}\n",
            ".topbar {\n  display: flex;\n  align-items: center;\n  margin-bottom: 16rpx;\n}\n"
            ".topbar > view + view,\n.topbar > text + text,\n.topbar > button + button {\n"
            "  margin-left: 16rpx;\n}\n",
        ),
        (
            ".meta {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 12rpx 24rpx;\n",
            ".meta {\n  display: flex;\n  flex-wrap: wrap;\n",
        ),
        (
            ".flags {\n  margin-top: 12rpx;\n  display: flex;\n  flex-wrap: wrap;\n  gap: 10rpx;\n}\n",
            ".meta > text {\n  margin: 0 24rpx 12rpx 0;\n}\n"
            ".flags {\n  margin-top: 12rpx;\n  display: flex;\n  flex-wrap: wrap;\n}\n"
            ".flags > text {\n  margin-right: 10rpx;\n}\n",
        ),
        (
            ".actions {\n  margin-top: 18rpx;\n  display: flex;\n  align-items: center;\n"
            "  gap: 14rpx;\n}\n",
            ".actions {\n  margin-top: 18rpx;\n  display: flex;\n  align-items: center;\n}\n"
            ".actions > view + view,\n.actions > text + text,\n.actions > button + button {\n"
            "  margin-left: 14rpx;\n}\n",
        ),
    ]),

    ('subpackages/admin/audit/audit.wxss', [
        (
            ".job-meta {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 20rpx;\n",
            ".job-meta {\n  display: flex;\n  flex-wrap: wrap;\n",
        ),
        (
            ".who {\n  display: flex;\n  align-items: center;\n  gap: 14rpx;\n"
            "  margin-top: 12rpx;\n}\n",
            ".job-meta > text {\n  margin: 0 20rpx 8rpx 0;\n}\n"
            ".who {\n  display: flex;\n  align-items: center;\n  margin-top: 12rpx;\n}\n"
            ".who > text + text {\n  margin-left: 14rpx;\n}\n",
        ),
    ]),

    ('subpackages/admin/import/import.wxss', [
        (
            ".field-row {\n  display: flex;\n  gap: 20rpx;\n}\n",
            ".field-row {\n  display: flex;\n}\n"
            ".field-row > view + view {\n  margin-left: 20rpx;\n}\n",
        ),
        (
            ".links {\n  display: flex;\n  gap: 24rpx;\n}\n",
            ".links {\n  display: flex;\n}\n"
            ".links > text + text {\n  margin-left: 24rpx;\n}\n",
        ),
        (
            ".result-rows {\n  display: flex;\n  flex-direction: column;\n  gap: 10rpx;\n",
            ".result-rows {\n  display: flex;\n  flex-direction: column;\n",
        ),
        (
            ".errs {\n  margin-top: 16rpx;\n  display: flex;\n  flex-direction: column;\n"
            "  gap: 8rpx;\n}\n",
            ".result-rows > text + text {\n  margin-top: 10rpx;\n}\n"
            ".errs {\n  margin-top: 16rpx;\n  display: flex;\n  flex-direction: column;\n}\n"
            ".errs > text + text {\n  margin-top: 8rpx;\n}\n",
        ),
    ]),
]


def main():
    total_ok = 0
    for rel, pairs in PLAN:
        path = os.path.join(MP, rel)
        with io.open(path, encoding='utf-8', newline='') as f:
            raw = f.read()
        # 统一用 \n 匹配（脚本里的 old/new 都按 \n 写），写回时还原原文件的换行风格
        eol = '\r\n' if '\r\n' in raw else '\n'
        src = raw.replace('\r\n', '\n')
        orig = src
        for i, (old, new) in enumerate(pairs):
            if old not in src:
                if new and new in src:
                    print('skip(已修复) %s #%d' % (rel, i))
                    continue
                print('!! MISS %s #%d -> %r' % (rel, i, old[:60]))
                return 2
            src = src.replace(old, new, 1)
            total_ok += 1
        if src != orig:
            with io.open(path, 'w', encoding='utf-8', newline='') as f:
                f.write(src.replace('\n', eol))
            print('written %s' % rel)
    print('replacements applied: %d' % total_ok)
    return 0


sys.exit(main())
