# vidlens

vidlens 把抖音 / B站视频变成 agent 可读的素材,供 Claude Code、Codex、DeepSeek Harness 等工具调用。本表定义项目语言。

## Language

**Bundle(素材包)**:
`prepare` 命令的完整产物集合——转写文本、帧图、拼图、manifest 与 context.md 的总和。
_Avoid_: context pack、context bundle、素材导读(导读只是其中一份文件)

**Agent 契约(Agent Contract)**:
vidlens 对调用方的完整承诺:stdout 恒为 JSON、五档退出码(0/1/2/3/4)、错误必带 hint、产物给绝对路径、绝不交互式提问。
_Avoid_: API 规范、输出格式(远不止格式,是行为承诺)

**Term Corrections(术语修正表)**:
把 ASR 误听映射为标准词的替换规则,内置表加 `--glossary` 注入。CLI 参数沿用历史名 `--glossary`,但概念上不得与本文档(GLOSSARY.md,领域词汇表)混淆。
_Avoid_: 词典、术语表(易与领域词汇表混淆)

## 知识库

**Entry(知识条目)**:
一个视频入库后的知识单元:事实层 + 结论层 + 元数据,目录名 `<YYYY-MM-DD>-<平台>-<视频ID>`。
_Avoid_: 素材包(那是 bundle)、文章、文档

**事实层(Source Layer)**:
Entry 中 bundle 产物的原样沉淀(转写、帧图、manifest、context.md,路径改写为相对路径)。永不覆盖。
_Avoid_: 原始层、数据层

**结论层(Conclusion Layer)**:
Entry 中 agent 基于事实层产出的分析结果,可删除、可重跑,挂在 `conclusions/` 下。
_Avoid_: 分析层、摘要层

**降级链(Fallback Chain)**:
抖音媒体下载的尝试顺序:无水印直链 → 带水印直链 → yt-dlp。所用层级会写入输出供调用方知悉。
_Avoid_: 重试策略(不是重试,是不同来源的有序尝试)
