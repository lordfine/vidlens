# vidlens

> **视频透镜** —— 把抖音 / B站视频变成 agent 读得懂的素材包:字幕(或语音转文字)、多颗粒度拆帧、综合分析上下文。

给 Claude Code、Codex、DeepSeek Harness 这类编码 agent 当"视频能力包":你负责理解与总结,vidlens 负责把素材准备好。

[![CI](https://github.com/lordfine/vidlens/actions/workflows/ci.yml/badge.svg)](https://github.com/lordfine/vidlens/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](pyproject.toml)
[![Platforms](https://img.shields.io/badge/platforms-%E6%8A%96%E9%9F%B3%20%C2%B7%20bilibili-orange)](#平台支持)

## 它做什么

```
 抖音/B站链接 ──▶ vidlens ──▶  ┌ transcript.(txt|srt|json)   语音转文字(本地 ASR)
                              ├ frames/*.jpg + 拼图          拆帧(四种颗粒度)
                              ├ manifest.json                机器可读的文件清单
                              └ context.md                   给 agent 的素材导读
```

- **字幕/转写**:平台 CC 字幕优先,没有则本地 SenseVoice 语音转文字(中英日韩粤,免登录免 API key)
- **拆帧**:`count`(均匀N帧)/ `fps` / `scene`(镜头切换,自动降阈值)/ `keyframe`,可出拼图总览
- **prepare 一站式**:字幕 + 拆帧 + manifest + context.md,按 coarse / medium / fine 三档颗粒度
- **为 agent 设计**:stdout 恒为 JSON、稳定退出码、错误带 `hint`、产物绝对路径、绝不交互式提问

## 快速开始

```bash
git clone https://github.com/lordfine/vidlens
cd vidlens
uv sync                 # 创建 .venv,自带静态 ffmpeg,无需系统依赖
uv run vidlens doctor   # 自检;ASR 模型首次转写时自动下载(~230MB,一次性)
```

一条命令出完整素材包:

```bash
uv run vidlens prepare "https://v.douyin.com/xxxx/" --granularity medium
```

支持完整链接、`v.douyin.com` / `b23.tv` 短链,甚至整段带噪音的分享文案。

## 命令

| 命令 | 用途 |
|---|---|
| `vidlens meta URL` | 元信息(标题/作者/时长/字幕轨),不下载 |
| `vidlens subs URL [--lang zh] [--format srt\|txt\|json]` | CC 字幕,无则 ASR 兜底 |
| `vidlens transcribe URL [--model sensevoice\|whisper-large-v3]` | 语音转文字 |
| `vidlens frames URL --mode count\|fps\|scene\|keyframe [--count 12] [--contact-sheet]` | 拆帧 |
| `vidlens prepare URL [--granularity coarse\|medium\|fine]` | 一站式素材包 |
| `vidlens cache list\|clean\|stats` | 缓存管理(媒体+转写双层缓存,LRU 2GB) |
| `vidlens doctor` | 自检 ffmpeg / 模型 / 网络 |

通用参数:`--cookie`(B站 SESSDATA / 抖音整段 cookie)、`--fresh`(跳过缓存)、`--glossary "误写=标准词"`(术语修正)、`--out DIR`。

## Agent 契约

- 成功:stdout 一个 JSON(`{"ok": true, ...}`);失败:stderr 一个 JSON 错误对象,`error.hint` 就是下一步动作
- 退出码:`0` 成功 · `1` 参数/内容问题 · `2` 需要登录(cookie) · `3` 反爬/网络 · `4` 依赖缺失(跑 doctor)
- 输出文档按 agent 阅读习惯排版:转写为 `[分:秒]` 锚点的自然段落;帧索引一行式;精确逐句时间轴在 `.srt`/`.json`
- 把 [SKILL.md](SKILL.md) 装进 agent 技能目录,agent 即可自主使用

## 平台支持

| 平台 | 匿名 | 带 cookie | 说明 |
|---|---|---|---|
| 抖音 | ✅(自动注册 ttwid) | 更稳 | iesdouyin 分享页解析 + 去水印直链下载;图集/直播不支持 |
| bilibili | ✅(≤480p,无AI字幕) | 1080p+AI字幕 | SESSDATA 解锁高清与 CC/AI 字幕;番剧/课程暂不支持 |

## 故障排查

- **transcribe 崩溃 / ORT API 版本错误**:本机 `C:\Windows\System32\onnxruntime.dll` 为旧版残留。vidlens 会自动把 venv 内新版复制到 DLL 搜索优先位置;若仍失败,删除或改名 System32 里的该文件(它不属于 Windows 本体)。
- **抖音 exit 3(风控)**:带 `--cookie`(浏览器 F12 → Network → 任意请求 → Request Headers → cookie 整段)重试。
- **ASR 出现 "code ex" 这类碎片/同音字**:内置 80+ 术语表会自动归一;领域词用 `--glossary "code ex=Codex;携修=邪修"` 修正。

## 开发

```bash
uv run pytest -q                    # 单元测试(离线)
VIDLENS_E2E=1 uv run pytest -q      # 真实链接 E2E(联网)
```

实现要点:抖音走 iesdouyin 分享页 `_ROUTER_DATA`(yt-dlp 对抖音不可用);ASR 用 sherpa-onnx SenseVoice(int8,长音频自动分块);ASR 后处理含术语归一与碎段合并;ffmpeg 用 imageio-ffmpeg 自带静态版。

## 致谢

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) · bilibili 提取与媒体下载
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) + [SenseVoice](https://github.com/FunAudioLLM/SenseVoice) · 本地语音识别
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) · 可选 Whisper 后端
- [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) · 免安装 ffmpeg

## License

[MIT](LICENSE)
