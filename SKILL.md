---
name: vidlens
description: 解析抖音/B站视频的 CLI 工具包:提取字幕或语音转文字、按多种颗粒度拆帧、生成供综合分析的视频素材包(subtitle/ASR + frames + manifest + context.md)。AI 总结由 agent 自己完成,本工具只准备素材。当用户要求"分析这个视频/总结视频内容/看看视频里说了什么/提取视频字幕/视频转文字"时使用。
---

# vidlens — 视频解析工具(agent 能力包)

## 启动检查

```bash
cd F:\vidlens
uv run vidlens doctor
```

- `status: "ok"` → 直接用
- ASR 模型未下载不是错误:首次 `transcribe/subs/prepare` 时自动下载(~230MB,一次性)

## 命令速查(全部输出 JSON)

```bash
uv run vidlens meta URL                        # 元信息+字幕轨,不下载。总是先跑这个
uv run vidlens subs URL [--lang zh] [--format srt|txt|json] [--no-asr]
uv run vidlens transcribe URL [--model sensevoice] [--lang auto]
uv run vidlens frames URL --mode count|fps|scene|keyframe [--count N] [--fps F] [--contact-sheet]
uv run vidlens prepare URL [--granularity coarse|medium|fine]   # 一站式素材包
uv run vidlens cache list|clean [--all]
```

URL 支持:完整链接、`b23.tv`/`v.douyin.com` 分享短链、含链接的分享文案。

## Agent 契约(必读)

- 成功:stdout 单个 JSON(`ok: true`);失败:stderr JSON,`error.hint` 就是下一步动作,**照做**
- 退出码:`0` 成功 · `1` 内容/参数问题 · `2` 需要登录(让用户给 cookie,`--cookie 'SESSDATA=...'` 或抖音整段) · `3` 反爬/网络(可重试/带 cookie) · `4` 依赖缺失(跑 doctor)
- 所有产物文件给出**绝对路径**;帧图片用多模态直接读,字幕/manifest 用文件读取
- 同 URL 自动缓存(媒体+转写);`--fresh` 强制刷新

## 典型工作流

### 用户:总结/分析这个视频
1. `prepare URL --granularity medium` (默认)
2. 读 `files.context_md` —— 里面有导读、带时间轴的语音全文、帧清单
3. 需要画面细节时按清单读 `frames_dir` 里的图片(或先看 `contact_sheet`)
4. **由你(agent)完成总结**,把时间轴字幕与关键帧对齐可以精确描述视频内容
5. 视频很长只要梗概 → `--granularity coarse`;要逐段精读 → `fine`

### 用户:只要字幕/文字稿
- 有 CC(极少,B站且多需登录):`subs URL`
- 否则:`subs URL` 会自动落到本地 ASR(等同 `transcribe`)
- 要精确时间轴选 `--format json/srt`,要直接可读选 `txt`

### 用户:看画面/镜头
- 均匀概览 `--mode count --count 12`;每 N 秒一帧 `--mode fps --fps 0.5`
- 镜头切换 `--mode scene`(自动降阈值);I 帧 `--mode keyframe`
- 拼图总览加 `--contact-sheet`(一张图看全片)

## 平台特性

- **抖音**:匿名自动注册 ttwid,多数视频可直接解析;被风控(exit 3)时让用户从浏览器 F12 复制整段 cookie 传 `--cookie`。图集/直播不支持(会明确报错)
- **B站**:匿名可解析但 >480p 清晰度与 AI 字幕需要 SESSDATA cookie;番剧/课程暂不支持
- ASR 引擎 SenseVoice:中英日韩粤混合,`--lang auto` 即可;唱歌内容的歌词识别质量有限(正常)

## 注意

- 长视频(>30min)的 prepare(fine) 会产生大量帧与较慢的转写;先用 coarse 确认方向
- 缓存位于 `%LOCALAPPDATA%\vidlens`,LRU 上限 2GB;`cache clean --all` 清空
- ffmpeg 无需安装(包内自带静态版);`vidlens_FFMPEG` 可覆盖
