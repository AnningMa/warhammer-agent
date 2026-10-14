# PDF ingestion

流程：原 PDF → Docling 解析快照 → 已核验修正 → 最终 TXT 与 JSONL → 后续 chunking。

## 唯一输出

```bash
uv run --locked python scripts/build_corpus.py
```

默认输出 `reports/core_rules.txt` 与 `reports/index_blocks.jsonl`，可用 `--output-dir PATH`。构建器验证原 PDF 和解析快照哈希，从原始 JSON 重建未修正页，在临时目录执行全部 36 页修正，最后删除临时生成的 MD、HTML、PNG 与审计 JSON。原有预览、历史导出、迁移报告不再是依赖。

`reports/` 只保留两个最终文件。原始资料保留在 `data/`，修正规则位于 `config/corrections/core_rules/`；这些是重建所需输入，不能作为重复语料入库。

## 内容与来源

60 页均纳入来源检查。`config/index_policy.json` 沿用历史 26 单元清单的排除页策略（1、2、3、4、31、40），初始生成 54 页的 263 个标题块；完成噪声清理和显式关联后保留 228 个规则块。旧 26 单元测试文件已删除，新 TXT 与 JSONL 内容保持一致；标题内容块仍需进一步切成检索 chunks。

有修正的页使用重新生成的修正结果，其余页从 `data/core_rules.docling.json` 导出，标记 `unreviewed`。混合修正页与未审查页的块标记 `partially_reviewed`；`reviewed_correction` 仅表示指定修正已核验，不表示全部图示语义已转为文本。历史处理器仍保留，因为不同页的图文、表格和策略卡修正无法用通用切分器替代。

统一块按 Markdown 标题边界组织。`text` 保留该块标题与正文；`embedding_text` 补入同页已有祖先标题。表格、策略卡、图片说明不按长度或空行拆分。标题上下文先逐页维护，再按 `config/corpus_relations.json` 显式关联跨页规则、表格与图注。

图片 Markdown 链接转换为原 PDF 页码引用，保留图注、不推断空间关系。`assets` 记录图片说明、原 PDF 页码、临时重建图片哈希和 `stored: false`；没有指向已删除 PNG 的路径。OCR 未启用。

每个 JSONL 记录含：

- `block_id`、`document_id`、`section_title`、`section_path`、`content_type`。
- `source_path`、`source_hash`、`document_path`、`document_sha256`、修正清单哈希、索引策略路径及哈希、关联配置路径及哈希。
- `page_number`、`page_numbers`：从 1 开始的物理 PDF 页码。
- `review_status`、`origin`、`warnings`。
- `txt_span`：`core_rules.txt` 中 `embedding_text` 的 Unicode 字符 `[start, end)`；`txt_sha256` 校验完整 TXT。
- `source_segments`：每个保留片段的原 `source_block_id`、页码、逐页 Markdown 哈希、`markdown_span`、原片段哈希、修正规则/审计哈希、原审查状态，以及其在最终块 `text` 中的 `text_span` 和渲染结果哈希。Markdown 范围与最终块范围不可混用。
- `source_block_ids`：该规则使用的初始块 ID；`associations`：已执行的关联配置项。
- 第一条 JSONL 的 `corpus_audit`：全部排除原因与原范围，仅用于审计，不进入 embedding。

初始块 ID 根据 PDF、页码、范围和内容确定；优化后的 `block_id` 根据保留片段、正文和关联配置哈希确定，可重复构建。输出 schema 为版本 3；已废弃块级的单页 `markdown_span` 与单页修正路径，改用 `source_segments`，避免合并块的错误来源归属。

## 噪声与关联配置

`config/corpus_relations.json` 固定 PDF/Docling 哈希和每个操作的初始块 ID、标题、页码、文本哈希。只有明确配置的独立页码/导航行被移除，纯图片和无正文标题不独立入库。保留数字的正文、表格和带说明图示。纯标题提供的已有上下文仍保留在子块 `embedding_text` 中。

配置包含第 9 页 D3 公式/表格、21–22 页 Wound Roll、33–34 页 Select Weapon、34–35 页 Make Attacks 的合并，以及第 54 页飞机移动图注向第 53 页移动规则的关联。不会自动把所有续页或相邻标题合并。来源变化会导致构建失败，需重新审查配置。

跨页片段分别保留原审查状态；`review_status` 汇总为 `partially_reviewed` 或原一致状态。图片资产的 `source_pdf_page` 指其实际来源页，可以与规则的首个 `page_number` 不同。

## 示例关联与地形上下文

优化规则块后，`config/rule_context.json` 用原来源块 ID、正文哈希和 PDF/Docling 哈希核验 UNIT COHERENCY 示例关联，以及第 45–48 页六类地形的明确范围。语料仍为 228 块。

示例的 `parent_rule_id` 与主规则的 `example_block_ids` 建立双向关联。查询使用原始 Top-K，然后通过 `related_evidence` 补充未返回的完整主规则，保留原页码、审查状态及来源片段；补充内容不参与向量排名。父规则缺失的部分索引会明确报错。

地形记录 `embedding_context`（terrain、rule），修复 Woods/Ruins 子规则缺失的地形标题路径。`embedding_text` 加入明确的地形/规则上下文，而原 `text`、正文哈希、`source_segments` 保持不变。`context_provenance` 指向提供名称的标题块及其来源片段，不冒充原文。不同地形的同文字规则分别保留。

配置改变或正文哈希不匹配时停止构建。上下文改变后重新生成最终 TXT 的精确范围与哈希；已有 embedding 索引必须重建。

## 下一步

仅从 `reports/index_blocks.jsonl` 切分。使用 `embedding_text`，继承来源元数据，新增 `chunk_id` 与父级 `block_id`。子块应记录自身精确范围；跨页合并记录每页来源，不能只保留一个页码。TXT 是阅读副本，不要和 JSONL 同时入库。

## 重新解析

```bash
uv run --locked python scripts/parse_pdf.py "data/Core Rules.pdf"
```

仅生成 `data/core_rules.docling.json`。首次解析可能下载模型，重新解析可能改变 JSON 哈希，既有修正规则将拒绝不匹配的输入，需重新审查。
