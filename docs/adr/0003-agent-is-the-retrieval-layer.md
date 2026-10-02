# agent 是检索层,vidlens 不建索引

知识库(分层见 ADR-0002)只做目录约定与 YAML frontmatter 元数据(平台/作者/日期/标签/视频ID),目录结构兼容 Obsidian vault 供人工浏览。不做内置 search 命令、不建索引(SQLite/向量库都不做):检索完全交给调用方 agent(文件系统 glob/grep/读文件)。

理由:本项目的设计前提就是"被 agent 调用",agent + 文件系统已是天然的全文本检索层;自建索引是重复建设,且语义级检索最终仍需 agent,索引永远到不了那个高度。Obsidian 兼容是几乎零成本的人工浏览赠品。
