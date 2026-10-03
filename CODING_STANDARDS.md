# Coding Standards

判断类规则,linter 管不了,review 时逐条对照。机械规则归 ruff(`E,F,W,I,UP,B,N`),此处不重复。

1. **错误必须落契约。** 平台层任何失败都要映射为 agent 契约错误(VidlensError 系:exit 0/1/2/3/4 + hint)。auth 类(需登录)一律 re-raise 为 `AuthNeededError`——严禁吞成 `BlockedError`;hint 按 ADR-0004 写成 agent 可执行指令(CDP 取 cookie 或请用户提供)。

2. **契约字段必须透传。** 平台 `download()` 的 `{path, source_level, retried}` 要出现在每个消费它的命令输出(frames/subs/transcribe)与 manifest;frames 的 `truncated/total_candidates` 同理。字段算出来了但没在输出露面 = bug。

3. **平台接口改动四处同步。** `douyin.py`、`bilibili.py`、`cli.py`、`prepare.py` 对 download 契约的消费是一套;改形状必须四处齐改——测试只覆盖部分路径,漏一处会带病上线(review 曾抓到主路径无锁与 auth 吞错两例)。
