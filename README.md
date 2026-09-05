# novel2Lens

本地小说文本分镜策划器：读小说 → 角色/场景/物品资产 → 上传参考图 → 首帧提示词（Qwen-Image-Edit-2511）+ MiniMax-H3 视频脚本。不调用 ComfyUI。

## 启动

资源管理器双击 `start.bat`，或在仓库根目录：

```powershell
.\start.ps1
```

脚本会：启动本地 **Qwen3.8-Flash-Next-UD**（llama-server `:8080`）→ 按需创建 `backend\.venv` / 安装依赖 → 拉起 API（8790）和前端（5176）→ 打开 http://127.0.0.1:5176。

只起模型：

```powershell
.\start-llm.ps1
```

关掉弹出的 `novel2Lens Flash-Next` / `API` / `UI` 窗口即停止服务。

手动分终端：

```powershell
.\start-llm.ps1
cd backend; python -m uvicorn app.main:app --host 127.0.0.1 --port 8790
cd frontend; npm run dev
```

## 本地模型

- 主模型：**Qwen3.8-Flash-Next-UD-IQ4_XS**，默认目录  
  `D:\Download\Quark\DownloadFiles\Qwen3.8-Flash-Next-UD 开源模型`  
  （可用环境变量 `N2L_FLASH_NEXT_DIR` 覆盖）
- API：`http://127.0.0.1:8080/v1`，模型名 `qwen3.8-flash-next`
- 未就绪时可降级到 Ollama `http://127.0.0.1:11434/v1` / `qwen2.5:32b`
- 上下文默认 `32768`（`N2L_LLM_CTX` 可改）
- 导出元数据记录 H3 编码器：`qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors`

## 测试

```powershell
cd backend
python -m pytest tests -q
```
