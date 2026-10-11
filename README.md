# ASR 音频采集小程序 · 快速上手

> 一句话：**双击一个脚本起后端 → 用微信开发者工具导入一个小程序目录 → 就能走通「登录 → 签同意书 → 领文本 → 录音 → 上传 → 审核 → 导出」全流程。**

工程位置：`E:/asr/`

---

## 一、三步跑起来

### 第 1 步：启动后端（首次约 1–3 分钟装依赖，之后秒起）

- **Windows**：双击 `E:\asr\start-server.bat`
- **macOS / Linux / Git Bash**：在 `E:/asr` 下执行

  ```bash
  bash start-server.sh
  ```

看到这一行就成功了：

```
Uvicorn running on http://0.0.0.0:8000
```

自检（另开一个终端）：`curl http://localhost:8000/health` → 返回 `{"status":"ok"}`

> 脚本会自动完成：建 `.venv` → 装依赖 → 由 `.env.example` 生成 `.env` → 以 `--reload` 启动。
> 重复运行是安全的（已存在则跳过建环境和生成 `.env`）。

### 第 2 步：导入小程序

1. 打开**微信开发者工具**（稳定版）。
2. 点「导入项目」→ 目录选 `E:/asr/asr-miniprogram`。
3. AppID 选「**测试号**」（`project.config.json` 里已内置 `touristappid`，并已关闭域名校验，模拟器可直接连本机后端）。
4. 点「编译」，模拟器出现登录页即成功。

### 第 3 步：走一遍完整演示

**通路 A · 普通用户（采集）**

| # | 操作 | 预期 |
|---|---|---|
| 1 | 点「微信登录（采集员）」 | 自动跳到《语音信息单独同意书》 |
| 2 | 勾选后点「同意并提交」 | 进入「我的任务」 |
| 3 | 点一条任务 → 录音 → 试听 → 提交 | 提示"上传成功" |

**通路 B · 管理员（导入任务 / 审核）**

| # | 操作 | 预期 |
|---|---|---|
| 4 | 返回登录页 → 点「管理员登录（演示）」 | **直接进入管理台**（管理员不采集，无需签语音同意书） |
| 5 | 管理台 →「导入任务」→ 上传 Excel（`序号`/`汉语文本` 两列）或粘贴文本 → 勾选「下发给」采集员 → 导入 | 建成任务包，并按人下发为子任务 |
| 6 | 换采集员账号登录 →「我的任务」 | **直接看到已下发的任务**，照文本录音（未指派的在「公共池」领取） |
| 7 | 管理台 →「录音审核」→ 试听 → 通过/退回 | 列表状态更新为"已通过"/"已退回" |
| 8 | 审核台点「导出」 | 生成含音频 + `metadata.csv` + `manifest.json` 的 ZIP |

> 第 4 步的"管理员登录"只在本机 dev 模式生效；生产走真实微信登录，角色由后端分配后按角色自动分流。

---

## 二、演示账号说明

| 账号 | 触发方式 | 角色 | 登录后落地页 |
|---|---|---|---|
| `u_demo` | 点「微信登录（采集员）」 | 采集员 collector | 同意书 → 我的任务（录音采集） |
| `u_admin` | 点「管理员登录（演示）」 | 管理员 admin | 管理台（导入任务 / 录音审核） |

生产环境：首位管理员由 `BOOTSTRAP_ADMIN_OPENIDS` 引导自动授予，之后用 `POST /api/admin/users/{id}/role` 调整。

---

## 三、目录结构

```
E:/asr/
├── start-server.bat / start-server.sh   # 一键启动后端
├── README.md                            # 本文件
├── ASR音频采集微信小程序实现方案.md        # 总体方案
├── 小程序项目档案.md                      # 工程现状档案（页面/接口/待办清单）
├── 真机录音参数验证清单.md                 # 真机验证 SOP
├── 任务导入格式说明.md                    # 管理员导入任务的格式与接口
├── 任务导入模板.csv                       # CSV 导入模板
├── asr-miniprogram/                     # 微信小程序（原生 + TypeScript，含管理端分包）
├── asr-server/                          # FastAPI 后端（PostgreSQL / 对象存储 / FFmpeg）
└── tools/
    ├── verify_recording.py              # 真机录音验证脚本
    ├── smoke_roles.py                   # 角色通路烟测（15 项）
    └── smoke_import.py                  # Excel 导入与统一下发烟测（17 项）
```

---

## 四、真机录音参数验证（你出设备，脚本收数）

```bash
# 在线模式：真机探针上报 → 后端 ffprobe 复核 → 脚本聚合出报告
python tools/verify_recording.py --api http://localhost:8000/api --token <JWT>

# 离线模式：把真机导出的音频放进一个目录，本机直接测
python tools/verify_recording.py --dir ./samples \
  --expect-format aac --expect-sample-rate 16000 --expect-channels 1
```

详细步骤见 `真机录音参数验证清单.md`。
**建议先装好 ffmpeg**（终端能跑 `ffmpeg -version` 即可），否则只能凭文件头判格式，拿不到真实采样率/声道。

---

## 五、管理员导入任务（格式）

任务包由管理员导入，**用 CSV，三列 `text, textId, assignee`**（UTF-8、首行表头）。模板见 `任务导入模板.csv`。

```csv
text,textId,assignee
今天天气真好，我们一起去公园散步吧。,,
请朗读这一段新闻：本地气温将明显下降。,t_demo_2,
你好，很高兴认识你，这是一段测试语音。,t_demo_3,u_demo
```

- `text` 必填（待录制文本）；`textId`、`assignee` 可留空（留空自动生成 / 进入公共池）。
- `assignee` 留空 → 任务进\u201c公共池\u201d，采集员可领取；填了 → 直接分配给该采集员。
- 接口：上传 `POST /api/admin/packages/import`、列表 `GET /api/admin/packages`、模板 `GET /api/admin/packages/template`。

完整说明（JSON 格式、curl 示例、约束）见 **`任务导入格式说明.md`**。

## 六、常见问题

- **端口 8000 被占用**：改脚本里的 `--port`，同时改 `asr-miniprogram/app.ts` 的 `baseUrl`。
- **真机预览连不上后端**：真机不能用 `localhost`。需把 `app.ts` 的 `baseUrl` 改成你电脑的**局域网 HTTPS 域名**，并在小程序后台配置 request / uploadFile / downloadFile 合法域名。
- **没装 ffmpeg**：转码会降级为 `skipped`，不阻断上传；装上后自动启用真实探测。
- **生产部署**：把 `.env` 的 `ENV` 改成 `prod`，填好 `JWT_SECRET` / `WX_APPID` / `WX_SECRET`，并设 `DEV_MOCK_LOGIN=false`；否则**启动会失败**（刻意的 fail-fast）。需要数据库/存储可用 `docker compose up -d` 起 PostgreSQL + MinIO。

---

## 七、发布上线（需真实账号与资质）

1. 注册小程序账号（mp.weixin.qq.com）→ 微信认证（企业 300 元/年）。
2. 换真实 AppID（改 `project.config.json` 的 `appid`），`baseUrl` 改 HTTPS 域名。
3. 小程序后台配置「服务器域名」，并发布《用户隐私保护指引》——**这是隐私弹窗生效的前提**。
4. 提交审核 → 发布（一般 1–7 天）。
> 语音属《个人信息保护法》中的敏感个人信息，务必按微信最新审核规范核对类目资质。

---

## 八、当前完成度

- ✅ 采集端全流程：登录 / 同意书（含撤回）/ 领文本 / 录音 / 试听 / 上传恢复 / `uploadId` 防重
- ✅ 平台隐私授权弹窗（录音前拦截）+ 麦克风权限被拒降级
- ✅ 后端：微信登录、任务、上传+转码+质检、审核、导出（含异步）、审计、角色鉴权、导出任务持久化、PIPL 单独同意门禁、生产密钥 fail-fast
- ✅ 角色通路分流：登录后按 `/auth/me` 角色自动进入采集端或管理台
- ✅ 管理台首页：身份/待审统计 + 导入任务、录音审核入口
- ✅ 导入任务：上传 Excel（`序号`/`汉语文本` 两列表）/ CSV / JSON，或粘贴多行文本（服务端用 openpyxl 解析 xlsx）
- ✅ 任务统一下发：勾选采集员后按人下发子任务——每人一份（`all`）或轮流分摊（`split`）；不指派则进公共池
- ✅ 采集端公共池领取（乐观锁防重复领取）
- ✅ 管理端审核台：试听（含 `?token` 播放）/ 通过 / 退回 / 导出
- ✅ 真机录音验证工装：脚本 + dev 探测接口 + 端侧探针
- ✅ 烟测脚本：`tools/smoke_roles.py`（15 项：两条通路 + 权限边界 + PIPL 门禁）、`tools/smoke_import.py`（17 项：xlsx 解析 + 三种下发方式）
- ⏳ 待做：真机现场验证、生产密钥托管（Vault/KMS）、真实 ASR 辅助审核
