# novel2Lens

本地小说文本分镜策划器：读小说 → 角色/场景/物品资产 → 上传参考图 → 首帧提示词（Qwen-Image-Edit-2511）+ MiniMax-H3 视频脚本。不调用 ComfyUI。

## 启动

终端 1：

```powershell
cd backend
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8790
```

终端 2：

```powershell
cd frontend
npm install
npm run dev
```

打开 http://127.0.0.1:5176

## 本地模型

- 主模型默认 `http://127.0.0.1:8080/v1` / `qwen3.8-flash-next`（llama-server）
- 未就绪时允许降级到 Ollama `http://127.0.0.1:11434/v1` / `qwen2.5:32b`
- 导出元数据记录 H3 编码器：`qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors`

## 测试

```powershell
cd backend
python -m pytest tests -q
```
