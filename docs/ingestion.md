# PDF ingestion

当前流程：探测 → Docling 解析 → 人工配置修正 → 清洗 Markdown / HTML / 审计 JSON。尚未实现向量索引或在线 Agent。

## 统一入口与配置

`python scripts/clean_pdf.py "data/Core Rules.pdf"` 按 manifest 调用所有修正规则；`--pages` 选择页码，`--rules` 可直接指定配置文件。未知页码或处理器会报错。

配置位于 `config/corrections/core_rules/page_XXX.json`，含 `schema_version` 和 `handler`。第一阶段统一入口、目录与来源管理，保留原有处理器及专有配置字段，避免在结构迁移中改变已核验语义。所有历史格式尚未转成一种内容块结构；这应在 RAG 入库层实施并单独验证。

- blocks：正文、表格、图片、策略卡。
- text：正文筛选与层级修正。
- figure / figures：图文分组；多图复用单图逻辑。
- visibility：来源图片子节点关联，坐标转换使用公共 geometry 模块。
- regions：按 PDF 坐标和字体提取；不能套用至所有页面。
- table / rule_table：已核验表格修正。

新增页面时先审查，再增加配置和 manifest 项；审查状态表示该页指定修正已核验，不表示所有图片语义均可用于文本 RAG。

## 删除与保留

已清洗页的原始 `reports/docling/pages/page_XXX.md` 是可重建导出物，可以删除。第 9 页处理器现在从原始 `document.json` 重建 Markdown，并核对既有 Markdown 哈希。审查工具在逐页 Markdown 缺失时也从 JSON 重建，不运行 PDF 模型解析。

保留原始 PDF、`reports/docling/document.json`、清洗审计 JSON、配置及来源哈希。保留未清洗页的 Markdown。原始整本文档 Markdown 是审计导出，不得与清洗页同时作为 RAG 索引输入。

重新运行 parse 会再次导出所有原始页，这是预期行为；确认新来源和清洗结果前，不自动删除新导出。

`reports/cleanup_manifest.json` 记录本次删除页的路径及哈希。`reports/migration_validation.json` 记录 36 页重建比较结果。

## 历史记录

`reviews/` 中记录反映当时的检查状态，其中旧脚本名仅为历史信息。当前命令以根 README 为准。

## 下一步

将各处理器输出转换为统一、带来源的内容块；增加全文页面审查状态和唯一索引来源清单，再做分块与检索评估。不要按文件名直接拼接原始全文与清洗页面。
