# vidtool

面向 agent 的视频解析 CLI —— 抖音 / B站优先。给 Claude Code、Codex、DeepSeek Harness
这类工具当"视频能力包"用:**工具只准备素材(字幕/语音转文字/拆帧),AI 理解与总结由 agent 完成**。

## 安装

```bash
cd F:\vidtool
uv sync            # 创建 .venv 并安装依赖(含 ffmpeg 静态二进制)
uv run vidtool doctor   # 自检;ASR 模型首次转写时自动下载(~230MB)
```

## 命令

```
vidtool meta URL                     # 元信息:标题/作者/时长/字幕轨(不下载)
vidtool subs URL [--lang zh] [--format srt|txt|json]   # CC字幕,无则本地ASR兜底
vidtool transcribe URL [--model sensevoice|whisper-large-v3]  # 语音转文字
vidtool frames URL --mode count|fps|scene|keyframe [--count 12] [--fps 0.5] [--contact-sheet]
vidtool prepare URL [--granularity coarse|medium|fine] # 一站式素材包+context.md
vidtool cache [list|clean|stats] [--all]
vidtool doctor
```

## Agent 契约

- 成功:stdout 一个 JSON 对象(`{"ok": true, ...}`)
- 失败:stderr 一个 JSON 错误对象,含 `error.hint`(下一步怎么办)
- 退出码:`0` 成功 · `1` 参数/内容问题 · `2` 需要登录(cookie) · `3` 反爬/网络 · `4` 依赖缺失
- 所有产物落盘,输出里给绝对路径(manifest);同 URL 自动缓存,`--fresh` 强制刷新
- cookie:`--cookie "SESSDATA=xxx"`(B站)/ 抖音整段 cookie;也可 `--cookie-file`
- 环境变量:`VIDTOOL_CACHE`(缓存根目录)、`VIDTOOL_FFMPEG`(ffmpeg 路径/目录)

## 给 agent 用

把 `SKILL.md` 装进 agent 的技能目录(或直接投喂),里面有为 agent 写的完整用法与工作流。

## 故障排查

- **doctor 全绿但 transcribe 崩溃/报 ORT API 版本**:本机 `C:\Windows\System32\onnxruntime.dll`
  是旧版残留。vidtool 会自动把 venv 内新版复制到搜索优先位置;若仍失败,删除或改名
  System32 里的 `onnxruntime.dll`(它不属于 Windows 本体)。
- **抖音 exit 3**:风控,带 `--cookie`(浏览器 F12 → Network → 任意请求 → Request Headers → cookie 整段)重试。
- **B站想要 1080p / AI 字幕**:同样需要 `--cookie 'SESSDATA=...'`。

## 测试

```bash
uv run pytest -q                    # 单元测试(离线)
VIDTOOL_E2E=1 uv run pytest -q      # 真实链接 E2E(联网,较慢)
```
