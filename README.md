# Warhammer Agent

Warhammer 40,000 规则书的解析与清洗已完成；下一阶段是 chunking、RAG 检索和 SQL Agent。

## 当前文件

- `reports/core_rules.txt`：最终可读文本，保留标题、表格、图注和 PDF 页码。
- `reports/index_blocks.jsonl`：后续 chunking 的唯一输入，228 个规则内容块，带来源哈希、审查状态和精确 TXT 字符范围。
- `data/`：原始 PDF、SQLite 数据库、计划 PDF，以及不可变的 `core_rules.docling.json` 解析快照。
- `config/corrections/core_rules/`：36 页已核验修正；`config/index_policy.json`：索引排除页策略。
- `src/warhammer_agent/ingestion/`、`scripts/`、`tests/`：重建文本需要的代码与测试。

## 重建最终文本

Requires Python 3.10+ and uv.

```bash
uv sync --locked
uv run --locked python scripts/build_corpus.py
```

此命令只输出上面的两个文件。中间 MD、HTML、PNG 和审计 JSON 在临时目录生成后自动清除，不需要保留 `reports/cleaned/` 或 `reports/docling/`。

图示引用指向原 PDF 页码，正文和图注保留；纯文本检索无法理解图中全部信息。`reviewed_correction` 表示指定修正已核验，其他页标记 `unreviewed`。

TXT 与 JSONL 使用同一份内容。TXT 的 `<<<RULE_BLOCK>>>` 分隔的是标题内容块，不是最终检索 chunk；历史 26 单元测试导出已移除。后续程序读取 JSONL 的 `embedding_text`，并继承来源元数据。

## 原始数据与辅助入口

原 PDF 与 SQLite 不纳入 Git。解析快照与修正规则需要保留，以支持不调用模型的重建。

`parse_pdf.py` 用于新 PDF 的 Docling 解析；`clean_pdf.py` 是构建器内部使用的修正入口。处理新 PDF 后必须重新核验修正规则和来源哈希。

详细格式见 [ingestion guide](docs/ingestion.md)；SQL 数据说明见 [data dictionary](docs/sql_data_dictionary.md)。

## 检查

```bash
uv run --locked python -m pytest -q
uv run --locked ruff check src scripts tests
uv run --locked ruff format --check src scripts tests
```

## 当前分块规则（已执行）

`<<<RULE_BLOCK>>>` 是 TXT 的输出分隔符。流程为逐页标题分块 → 清理噪声 → 按已确认的关系合并规则与表格/图注，JSONL 每行与 TXT 一个分隔段一一对应。当前有 228 个规则块，尚未按 300–500 tokens 二次切分。

1. 检查原 PDF 与 Docling JSON 的 SHA-256；36 个有核验修正的页从修正规则重建，其他页从原始 JSON 导出。
2. 按物理 PDF 页序读取；排除 `config/index_policy.json` 中的 1、2、3、4、31、40 页，得到 54 页的 263 个初始标题块。
3. 遇到行首 `#` 至 `######` 标题开始新块；代码围栏内的标题不切分。同标题下的段落、列表、表格和图注不按空行切开，策略卡的 WHEN、TARGET、EFFECT、RESTRICTIONS 保持完整。
4. 删除独立无图注的图片占位、无正文的纯标题/纯图片块；纯标题仍通过已有标题路径为子规则提供上下文。页码、导航数字和页眉只删除 `config/corpus_relations.json` 中明确指定的行，保留表格与规则中的数值。移除第 59 页独立的 MISSION 标签。
5. 按关联配置合并 DICE 与 D3 表格（第 9 页）；合并 Wound Roll 说明、表格与续文（21–22 页）、Select Weapon 续文（33–34 页）、Make Attacks 续文（34–35 页）。第 54 页飞机移动图与说明移入第 53 页飞机移动规则，冲锋/战斗正文保留。关联操作核对原块 ID 与文本哈希，来源改变时停止，不能静默套用旧规则。
6. 图片链接改为原 PDF 页码引用；保留图注，不推断图片空间关系。跨页断开的同一句话用空格接续，其余片段保持段落和表格边界。不进行任意相邻规则合并，不按长度截断，不增加 overlap。
7. `source_segments` 为每个保留片段记录原页码、原 Markdown 范围、哈希及审查状态；`page_numbers` 包含完整来源页码。混合已修正与未审查页的块标记 `partially_reviewed`，不升级为全块已核验。`txt_span` 精确定位最终 TXT 中的 `embedding_text`。
8. 263 个初始块中，30 个无有效规则文本的块被排除，5 个原块并入其他规则，得到 228 块。删除记录放在第一条 JSONL 的 `corpus_audit` 元数据中，`reports/` 仍然只保留 TXT 与 JSONL。

Embedding 入口以“一规则块 → 一向量”为基线，读取 JSONL 的 `embedding_text`。来源片段、排除审计、Block ID 和 TXT 包装不会输入模型；两种 provider 使用同一份语料。此次语料变化后，之前生成的向量需重新构建，查询入口会拒绝使用旧语料哈希的索引。

## 示例与地形上下文优化（已执行）

`config/rule_context.json` 使用初始来源块 ID、正文哈希、PDF/Docling 哈希确认关联，共保留 228 个块。

- 单位一致性示例仍是独立块，`parent_rule_id` 指向完整 UNIT COHERENCY 主规则，主规则保存 `example_block_ids`。查询命中示例时，程序在 `related_evidence` 补充主规则的全文、页码及来源片段；若主规则已经在原始 Top-K 中，不重复添加。补充证据不伪造相似度分数，不改变原始排名。
- 第 45–48 页的 6 类地形按原 PDF 标题确定范围，地形块记录 `embedding_context`（terrain、rule）。WOODS 与 RUINS 的 FOOTPRINT、MOVEMENT、VISIBILITY、BENEFIT OF COVER 等块补齐地形名称与标题路径，保持各自适用范围。
- 文档嵌入文本采用 `Terrain: 地形名称\nRule: 规则标题\n\n原正文`。原 `text`、正文哈希和 `source_segments` 均不改写；`context_provenance` 单独保存提供名称的标题块、原页码、来源片段与配置哈希。新增上下文不是原规则正文。
- 同文字的 Woods/Ruins 掩体规则分别保留；本次不合并不同地形，也不执行结果去重。

本次更新后必须重建已有向量索引。以 Qwen 为例：

```bash
uv run --locked --extra qwen python scripts/embed_rules.py --provider qwen
uv run --locked --extra qwen python scripts/embed_rules.py --provider qwen --evaluate --top-k 5
uv run --locked --extra qwen python scripts/embed_rules.py --provider qwen --query "How close must models in a unit stay to one another?" --top-k 1
```

`hit_rate` 和 `mrr_at_k` 仍只计算原始向量排名；新增 `evidence_hit_rate` 计算原始结果与显式补充主规则的并集中是否包含指定目标块。它是来源块覆盖指标，不是生成回答准确率。测试新增垂直距离、大单位一致性、Woods/Ruins 掩体和通用掩体例外问题，共 18 题。

## Embedding 配置与调用

公开配置：`config/embeddings.json`。密钥填写在根目录 `.env` 的 `GEMINI_API_KEY=` 后；模板是 `.env.example`，`.env` 已加入 Git 忽略。代码优先读取环境变量，不覆盖已有环境配置。Qwen 本地推理不需要 API key。

默认都使用 768 维，并进行 L2 归一化，便于分别使用余弦相似度检索。**相同维度不代表相同向量空间**：两种模型的向量分别保存在 `storage/embeddings/gemini.npz` 和 `qwen.npz`，查询必须使用对应模型。来源、模型配置或检索指令变动后，程序要求重建索引。

### Gemini：云端 `gemini-embedding-2`

```bash
uv sync --locked --extra gemini
uv run --locked --extra gemini python scripts/embed_rules.py --provider gemini --dry-run
# 填写 .env 后，先实际调用 3 块；另存 gemini-smoke.npz
uv run --locked --extra gemini python scripts/embed_rules.py --provider gemini --limit 3
# 再构建完整索引
uv run --locked --extra gemini python scripts/embed_rules.py --provider gemini
uv run --locked --extra gemini python scripts/embed_rules.py --provider gemini --query "When can I use the Grenade stratagem?"
```

使用官方 `google-genai` SDK。文档格式为 `title: 标题路径 | text: embedding_text`，查询格式为 `task: search result | query: 问题`；Embedding 2 不使用旧版 `task_type` 参数。每块单独请求，避免多个字符串合成一个向量。默认请求超时 30 秒、最多 3 次尝试，重试由 SDK 管理；`request_interval_seconds` 可按账户配额调大。[官方输入格式与聚合说明](https://ai.google.dev/gemini-api/docs/embeddings)

模型支持最多 8192 tokens。本代码额外采用更保守的 8192 UTF-8 字节输入保护（包含标题与格式前缀），超限直接报错，要求先细分块；这是本地保护值，不是精确 token 计数。如果 API 返回截断标记也会拒绝保存。[模型限制](https://ai.google.dev/gemini-api/docs/models/gemini-embedding-2)

### Qwen：本地 `Qwen/Qwen3-Embedding-0.6B`

```bash
uv sync --locked --extra qwen
uv run --locked --extra qwen python scripts/embed_rules.py --provider qwen --dry-run
# 首次真实调用将下载模型到 storage/models/，之后复用缓存
uv run --locked --extra qwen python scripts/embed_rules.py --provider qwen --limit 3
uv run --locked --extra qwen python scripts/embed_rules.py --provider qwen
uv run --locked --extra qwen python scripts/embed_rules.py --provider qwen --query "When can I use the Grenade stratagem?"
```

使用 `SentenceTransformer` 加载模型，默认 CPU、batch_size=4、max_seq_length=8192。模型本身支持 32K，但项目默认保留较小上限控制本地资源；推理前使用模型 tokenizer 检查完整输入，超限报错，不让编码器静默截断。

文档直接编码 `embedding_text`；查询使用 `Instruct: 英文检索指令\nQuery:问题`。从模型输出取前 768 维，再归一化。模型缓存完成后，将 `local_files_only` 设为 `true` 可禁止再次下载。仓库默认安装 CPU 版 PyTorch；使用 CUDA 还需要另行配置兼容的 GPU PyTorch 环境，仅修改 `device` 不足以启用 GPU。[官方加载方法与检索指令](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)

也可以直接在 Python 中复用相同接口：

```python
import json
from pathlib import Path
from warhammer_agent.embeddings.providers import create_embedder

provider = "qwen"  # 或 "gemini"
config = json.loads(Path("config/embeddings.json").read_text())
embedder = create_embedder(provider, config[provider], Path.cwd())
try:
    query_vector = embedder.embed_query("Can an Assault weapon shoot after advancing?")
finally:
    embedder.close()
```

`--dry-run` 不调用 API、不下载模型，只检查输入与配置；Qwen 精确 token 检查在加载模型 tokenizer 后执行。运行产物只写入已忽略的 `storage/`，`reports/` 仍然保留两个文件。当前保存的是可查询的 NPZ 向量基线，尚未接入 ChromaDB 或在线 Agent。

## Gemini 与 Qwen 的实际选择

截至 2026-10-14，以下价格来自官方页面；速度和本项目效果尚未实测。

| 比较项 | Gemini Embedding 2 | Qwen3-Embedding-0.6B 本地 |
|---|---|---|
| 操作难度 | 安装 SDK、申请并填写 API key；维护限流和网络即可 | 安装推理依赖、首次下载模型、管理内存和缓存；CPU 可运行 |
| API 成本 | 标准文本 $0.20/百万 tokens；Batch $0.10/百万 tokens；有免费层级，受账户配额约束 | 本地没有按 token 收取的 API 费用；占用磁盘、内存、电力与计算时间 |
| 当前代码计费方式 | 使用标准逐块 API，不是官方 Batch API | 本地按 batch_size 分批推理 |
| 硬件与速度 | 不需要本地模型算力；228 块需要逐块请求，耗时受网络和配额影响 | 首次下载权重较大；0.6B 权重按 FP16 粗估约 1.2 GB、FP32 约 2.4 GB，运行内存还需激活与框架；CPU 延迟需实测 |
| 数据传输 | 将文档文本和查询提交 Google；免费层级数据使用政策与付费层级不同 | 缓存完成后可离线编码，文档和查询在本机处理 |
| 能力 | 多语言、多模态；本项目当前只使用文本，不自动理解 PDF 图示 | 多语言文本 embedding，适合本地与跨语言检索 |
| 向量设置 | 官方默认 3072 维，本项目请求 768 维 | 官方最高 1024 维，本项目取 768 维再归一化 |
| 检索质量 | 必须在本规则库测试，不能只凭通用榜单保证准确率 | 同样必须测试，不能仅凭“免费/本地”判断效果 |

[Google 官方价格与数据使用政策](https://ai.google.dev/gemini-api/docs/pricing)；[Qwen 官方模型说明](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)。权重大小是参数量的粗估，不是本机内存测量。若假设本次文本嵌入共消耗 50,000 tokens，Gemini 标准费用约 $0.01；实际取决于 API 分词、标题前缀、查询、重试和免费额度。

建议先用 Gemini 跑通流程，同时用 Qwen 做本地对照。当前语料很小，分块完整性、关键词检索与重排可能比单纯换大模型更值得优化；具体收益以测试结果为准。

### 使用同一组问题比较效果

`tests/eval_cases/retrieval.json` 保存 18 个英文规则问题和唯一目标块（页码 + 标题）。两种索引都完整构建后运行：

```bash
uv run --locked --extra gemini python scripts/embed_rules.py --provider gemini --evaluate --top-k 5
uv run --locked --extra qwen python scripts/embed_rules.py --provider qwen --evaluate --top-k 5
```

输出原始命中率 `hit_rate`、`mrr_at_k`、补充证据覆盖率 `evidence_hit_rate` 与逐题排名。它们只检查这 18 题的指定目标块，不代表全书召回率、回答忠实度或全部正确答案覆盖度。比较时保持相同 corpus、维度、问题、top-k 和完整索引；两模型的原始相似度分数不能直接横向比较。
