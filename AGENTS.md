# vidlens — agent guide

- 语言权威是 [GLOSSARY.md](GLOSSARY.md):改任何接口前先读,词条的 `_Avoid_` 列表是禁用词
- 不可逆决策在 [docs/adr/](docs/adr/);与改动冲突时先看对应 ADR
- 判断类编码规则(review 依据):[CODING_STANDARDS.md](CODING_STANDARDS.md)
- 检查:`uv run ruff check src tests` · `uv run pytest -q`(离线;真实链路加 `VIDLENS_E2E=1`)
- 平台模块(douyin/bilibili)的 `download()` 契约:`{path, source_level, retried}`,详见 CODING_STANDARDS
