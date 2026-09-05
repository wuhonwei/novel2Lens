# 内嵌文生图 / 图片编辑管线 Design

**Date:** 2026-09-05  
**Status:** Approved (user)  
**Supersedes:** `2026-09-05-asset-image-gen-design.md`（对接造像 HTTP；本设计改为本仓库内嵌，不再依赖 aiImage `:8000`）

## Goal

在 novel2Lens 内嵌文生图（T2I）与图片编辑（I2I），经本机 ComfyUI 出图：

- **一键生成**：结果直写资产槽位（无需确认）；先跑完全部文生图，再切换编辑模型跑半身/近景。
- **手动编辑**：最多 3 张参考图 → 生成新图 → 直写目标槽位；选图默认指向「图片输出目录」。
- **保留**每槽删除、手动上传。
- **全局串行队列**（同时只跑 1 个 Comfy 任务）；刷新后仍显示生成/加载状态。
- **硬互斥**：图任务期间文字模型歇着；Comfy **默认不常驻**，按需启动；T2I / Edit 模型按阶段加载，**空闲 3 分钟自动卸载**。

## Non-goals

- 不再启动或 HTTP 调用造像（aiImage `:8000`）。
- 不做多候选挑选确认 UI。
- 不把 ComfyUI 源码打进本仓库（仍使用外置 `D:\Develop\ComfyUI`，端口 **8189**）。
- 物品不做近/远双槽；不做多 GPU 并行。
- 不引入本版以外的新扩散后端。

## Architecture

```
前端书级资产
  ├─ 一键生成 / 单槽重生成 / 手动编辑(≤3图) / 上传 / 删除
  └─ 轮询：排队中 | 文生图模型加载中 | 图片编辑模型加载中 | 生成中 | 失败
        ↓
FastAPI :8790
  ├─ image_jobs（SQLite，可刷新恢复）
  ├─ ImageWorker（单线程，concurrency=1）
  ├─ ComfySupervisor（按需启停 Comfy 进程 + /free 卸载）
  ├─ LlmSupervisor（图任务期间停 Flash-Next；空闲后懒启动）
  └─ 结果直写 Asset 槽位
        ↓
ComfyUI :8189（外置；默认不随 start.ps1 常驻）
```

从造像（`D:\Develop\aiImage`）**抄入并适配**的最小集合：

- `comfy` 客户端、`workflows` 编译、`character_prompt` / `ideogram_prompt`、QA（可先精简）、三份 workflow JSON  
- 路径建议：`backend/app/comfy_pipeline/` + `backend/workflows/`

删除/停用：`zaoxiang_client.py` 对造像的依赖；`start.ps1` 中启动造像的逻辑。

## Slot model & aspects

| 资产 kind | 文生图 | 再编辑 |
|-----------|--------|--------|
| character | `full_path` **9:16** | `half_path` **3:4**（源=全身） |
| scene | `far_path` **16:9** | `near_path` **3:4**（源=远景） |
| prop | `image_path` **1:1** | （一键不编辑） |

- 场景字段：新增 `far_path` / `near_path`；旧 `image_path` 迁移策略：若仅有 `image_path`，视为远景读入 `far_path`（兼容一轮）。
- 分镜参考：角色 half/full 二选一不变；场景优先 `near`，否则 `far`。
- 「核心」人物/场景/物品：一键范围 = 当前项目书级资产列表中对应 kind（与现「一键生成参考图」同一批；不另加 core 标记，除非后续产品要求）。

## One-click pipeline

1. 入队：按资产顺序生成 **全部 t2i jobs**（角色全身、场景远景、物品），再生成 **全部 edit jobs**（半身、近景）。同批共享 `batch_id`。
2. Worker FIFO，全局同时仅 1 个 running。
3. 阶段切换：从 t2i 批转到 edit 批（或反向）前：`ComfyClient.free_memory()`，再加载另一侧模型（见下节）。
4. 成功：立即写入对应 `*_path`，刷新 shot readiness。失败：写 `error`，默认 **不中断同批后续**。
5. 半身/近景缺源图：先补对应 t2i，再 edit。

## Manual edit

- 入口：资产卡「编辑生成」。
- 参考图 ≤3：优先从「图片输出目录」列目录勾选；另提供本机文件选择。浏览器无法强制 file picker 根目录时，以目录列表 + 上传为正式方案。
- 提示词、目标槽位、aspect 默认按目标槽。
- 入队 `kind=edit`；完成后直写目标槽；保留删除/上传。

## Queue persistence (`image_jobs`)

| 字段 | 含义 |
|------|------|
| id, project_id, asset_id | 关联 |
| kind | `t2i` \| `edit` |
| target_field | `full` \| `half` \| `far` \| `near` \| `image` |
| status | `queued` \| `running` \| `succeeded` \| `failed` \| `cancelled` |
| phase | 可选：`ensuring_comfy` \| `loading_t2i` \| `loading_edit` \| `generating`（供前端文案） |
| prompt, payload_json, error, batch_id | 载荷与错误 |
| created_at, updated_at | 时间 |

API 入队后立即返回 job/batch（**不**同步阻塞到出图结束）。  
`GET` active jobs（或 bundle 内嵌 `active_image_jobs`）供刷新恢复。

进程重启：原 `running` → `failed`（或重新 `queued`，实现取 failed + 可重试）；`queued` 保留。

## Comfy lifecycle（按需、非常驻）

**默认**：`start.ps1` **不**启动 ComfyUI；也不启动造像。

| 事件 | 行为 |
|------|------|
| 首个图任务将 running | 若 `:8189` 不可达 → 启动 `D:\Develop\ComfyUI`（与造像脚本同路径约定，可配置）→ 等到 health |
| 进入 t2i job | 若当前未加载文生图后端：标记 `loading_t2i`，提交 T2I workflow（Comfy 冷加载 checkpoint） |
| 进入 edit job | 先 `/free`（若上一阶段为 t2i）→ 标记 `loading_edit` → 提交 Edit workflow |
| 任意图任务成功/失败后 | 刷新 **last_image_activity_at** |
| 空闲 ≥ **180s**（无 queued/running） | 后台：`free_memory()` 卸载模型；若配置 `stop_comfy_when_idle=true`（**默认 true**）再停止 Comfy 进程，释放内存 |
| 空闲计时内又来新任务 | 取消卸载；若进程已停则再次按需启动 |

前端状态文案（优先级从高到低示意）：

1. `文生图模型加载中`（phase=`loading_t2i` 或 ensuring + 即将 t2i）
2. `图片编辑模型加载中`（phase=`loading_edit`）
3. `排队中` / `生成中`
4. `失败` + 短错误

顶栏显示全局队列摘要（n/m、当前资产名、上述 phase）。

## LLM hard mutex

- 存在任意 `queued`/`running` 图任务时：
  - 扫库 / 提取 / 分镜等 LLM API → **409**，文案：「参考图生成中，请稍后再试」
  - 停止 Flash-Next（`llama-server`，与 `start-llm.ps1` 同一端口/PID 约定）
- 图队列空后：**不**自动常驻拉起 LLM；下次文字请求时懒启动（或用户手动 `start-llm.ps1`）。
- 前端：图任务进行中禁用文字类操作并显示同一提示。

文字模型与图片模型 **不得**同时处于「已加载可用」状态：图任务开始前卸 LLM；LLM 懒启动前若 Comfy 仍占着模型则先 `/free`（及按策略停 Comfy）。

## Error handling

| 情况 | 行为 |
|------|------|
| Comfy 启动失败 | job `failed`，顶栏提示检查 Comfy 路径/端口 |
| OOM / 超时 | `/free`，有限重试后 `failed`，同批继续 |
| 取消本批 | queued→cancelled；running→interrupt+cancelled |
| 删除正在生成的槽 | 取消对应该槽的 active jobs |

## UI summary

- 去掉造像 `:8000` 依赖文案 → 「按需启动 ComfyUI :8189」。
- 一键：进度 + 可取消本批；状态含模型加载中。
- 资产卡：角色全身/半身；场景远景/近景；物品单图；每槽重生成/上传/删除；「编辑生成」。
- 成功直写，无确认弹窗。

## Testing

- 串行：两 job 不同时 `running`。
- 一键入队顺序：全部 t2i 在全部 edit 前。
- t2i↔edit 切换调用 `free_memory`。
- 空闲 3 分钟触发卸载（测时用缩短阈值）。
- 有 active 图任务时 LLM → 409。
- far/near、full/half 字段与比例。
- 刷新后 active jobs + phase 仍可查。
- Fake Comfy / Fake LLM supervisors，不真跑 GPU。

## Start scripts

- `start.ps1`：backend + frontend；**不**默认起造像、**不**默认起 Comfy、**不**默认起 LLM。
- 保留 `start-llm.ps1`；Comfy 由 ImageWorker/ComfySupervisor 按需拉起。
- 配置项：`comfy_base_url`、`comfy_root`、`image_idle_unload_seconds=180`、`stop_comfy_when_idle=true`。

## Migration from current code

1. 替换 `image_gen.py` / `zaoxiang_client.py` 为内嵌 pipeline + job queue。
2. Asset 增加 `far_path`/`near_path`；场景就绪与 shot_refs 更新。
3. API：异步入队 + jobs 查询；废弃同步「等造像 poll 完再返回」语义。
4. 前端：队列轮询、phase 文案、场景双槽、编辑面板。
5. 文档与旧 spec 标注 superseded。
