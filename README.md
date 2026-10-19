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
uv run --locked --extra qwen --extra chroma python scripts/embed_rules.py --provider qwen
uv run --locked --extra qwen --extra chroma python scripts/embed_rules.py --provider qwen --evaluate --top-k 5
uv run --locked --extra qwen --extra chroma python scripts/embed_rules.py --provider qwen --query "How close must models in a unit stay to one another?" --top-k 1
```

`hit_rate` 和 `mrr_at_k` 仍只计算原始向量排名；新增 `evidence_hit_rate` 计算原始结果与显式补充主规则的并集中是否包含指定目标块。它是来源块覆盖指标，不是生成回答准确率。测试新增垂直距离、大单位一致性、Woods/Ruins 掩体和通用掩体例外问题，共 18 题。

## ChromaDB 向量存储（默认后端）

本地数据库目录为 `storage/chroma/`，包含 `chroma.sqlite3` 与索引文件。它们均被 Git 忽略，不放进 `reports/`。当前 Qwen 的 228 条、768 维向量已从匹配当前语料的 `storage/embeddings/qwen.npz` 导入，没有重新计算文档 embedding。

```bash
uv sync --locked --extra chroma --extra qwen
# 从已有 NPZ 导入，或重复导入；不加载 embedding 模型、不调用 API
uv run --locked --extra chroma python scripts/embed_rules.py --provider qwen --import-npz
# 默认从 Chroma 检索并补充关联主规则
uv run --locked --extra chroma --extra qwen python scripts/embed_rules.py --provider qwen --query "When can I use the Grenade stratagem?"
# 可按明确的地形名称过滤
uv run --locked --extra chroma --extra qwen python scripts/embed_rules.py --provider qwen --query "When do I gain cover?" --terrain WOODS
# 同一组题验证 Chroma 和 NPZ；这两条命令会分别编码查询
uv run --locked --extra chroma --extra qwen python scripts/embed_rules.py --provider qwen --evaluate
uv run --locked --extra qwen python scripts/embed_rules.py --provider qwen --backend npz --evaluate
```

配置位于 `config/embeddings.json` 的 `backend` 和 `chroma`：默认路径 `storage/chroma`，集合基础名称 `core_rules_qwen` / `core_rules_gemini`。实际集合名自动追加语料哈希与模型配置指纹，避免旧内容或不同模型混用。旧版本集合保留，不自动删除。试运行使用独立的 `_smoke` 集合。

`--import-npz` 会核对 NPZ 的配置指纹、语料哈希和完整记录内容，采用预计算向量与原 `embedding_text` 导入；重复导入使用 upsert，清除该版本集合中的多余记录。索引在写入完成前标记为 building，不供查询。新建 embedding 时，默认同时写 NPZ 备份与 Chroma；指定 `--backend npz` 则只写 NPZ。

Chroma 禁用自动 embedding，查询仍通过项目的 Qwen/Gemini provider 编码，以保留检索指令和维度设置。检索使用数据库 HNSW cosine 距离，输出 `score = 1 - distance`；由于近似检索与浮点精度差异，排序不应假定永远与 NPZ 完全一致。

用于过滤的地形、审查状态、文档标识和首个页码单独存储；跨页页码及完整的 `source_segments`、审计、上下文与示例关系保存在 `block_json` 中，读取时恢复原始结构。`page_number` 仅表示首个来源页，完整引用仍使用 `page_numbers`。命中示例后通过数据库按 ID 取主规则；不会把父规则伪装成向量检索第一名。

## Embedding 配置与调用

公开配置：`config/embeddings.json`。密钥填写在根目录 `.env` 的 `GEMINI_API_KEY=` 后；模板是 `.env.example`，`.env` 已加入 Git 忽略。代码优先读取环境变量，不覆盖已有环境配置。Qwen 本地推理不需要 API key。

默认使用本地 Chroma、768 维与 cosine 距离。两种模型使用独立 collection，按语料哈希与模型配置指纹隔离版本；完整来源 JSON 和示例关联保存在每条记录中。NPZ 继续保存在 `storage/embeddings/`，作为精确检索基线和备份。**相同维度不代表相同向量空间**，查询必须使用对应模型。来源、模型配置或检索指令改变后，需要导入匹配版本或重新构建。

### Gemini：云端 `gemini-embedding-2`

```bash
uv sync --locked --extra gemini --extra chroma
uv run --locked --extra gemini --extra chroma python scripts/embed_rules.py --provider gemini --dry-run
# 填写 .env 后，先实际调用 3 块；另存 gemini-smoke.npz
uv run --locked --extra gemini --extra chroma python scripts/embed_rules.py --provider gemini --limit 3
# 再构建完整索引
uv run --locked --extra gemini --extra chroma python scripts/embed_rules.py --provider gemini
uv run --locked --extra gemini --extra chroma python scripts/embed_rules.py --provider gemini --query "When can I use the Grenade stratagem?"
```

使用官方 `google-genai` SDK。文档格式为 `title: 标题路径 | text: embedding_text`，查询格式为 `task: search result | query: 问题`；Embedding 2 不使用旧版 `task_type` 参数。每块单独请求，避免多个字符串合成一个向量。默认请求超时 30 秒、最多 3 次尝试，重试由 SDK 管理；`request_interval_seconds` 可按账户配额调大。[官方输入格式与聚合说明](https://ai.google.dev/gemini-api/docs/embeddings)

模型支持最多 8192 tokens。本代码额外采用更保守的 8192 UTF-8 字节输入保护（包含标题与格式前缀），超限直接报错，要求先细分块；这是本地保护值，不是精确 token 计数。如果 API 返回截断标记也会拒绝保存。[模型限制](https://ai.google.dev/gemini-api/docs/models/gemini-embedding-2)

### Qwen：本地 `Qwen/Qwen3-Embedding-0.6B`

```bash
uv sync --locked --extra qwen --extra chroma
uv run --locked --extra qwen --extra chroma python scripts/embed_rules.py --provider qwen --dry-run
# 首次真实调用将下载模型到 storage/models/，之后复用缓存
uv run --locked --extra qwen --extra chroma python scripts/embed_rules.py --provider qwen --limit 3
uv run --locked --extra qwen --extra chroma python scripts/embed_rules.py --provider qwen
uv run --locked --extra qwen --extra chroma python scripts/embed_rules.py --provider qwen --query "When can I use the Grenade stratagem?"
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

`--dry-run` 不调用 API、不下载模型，只检查输入与配置；Qwen 精确 token 检查在加载模型 tokenizer 后执行。运行产物只写入已忽略的 `storage/`，基线语料在 `reports/` 保留原有两个文件；父子块实验另增一个 JSONL。默认写入 Chroma 持久化向量库，并保留可查询的 NPZ 基线；在线 Agent 尚未实现。

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
uv run --locked --extra gemini --extra chroma python scripts/embed_rules.py --provider gemini --evaluate --top-k 5
uv run --locked --extra qwen --extra chroma python scripts/embed_rules.py --provider qwen --evaluate --top-k 5
```

输出原始命中率 `hit_rate`、`mrr_at_k`、补充证据覆盖率 `evidence_hit_rate` 与逐题排名。它们只检查这 18 题的指定目标块，不代表全书召回率、回答忠实度或全部正确答案覆盖度。比较时保持相同 corpus、维度、问题、top-k 和完整索引；两模型的原始相似度分数不能直接横向比较。

## 完整规则父块 + 检索子块实验

独立配置为 `config/parent_child.json`，新文件为 `reports/parent_child_blocks.jsonl`；原来的 `index_blocks.jsonl` 和基线集合继续保留。新 JSONL 使用 `record_type=parent/child` 区分记录：父块保留全部 228 个现有规则块的正文、跨页关联与来源；只有子块生成向量。示例仍通过原有 `parent_rule_id` 补充主规则，检索子块通过独立的 `parent_block_id` 关联完整父块。

执行规则：

- 用 Qwen 模型自己的 tokenizer 计数，包含 embedding 标题前缀。完整输入不超过 **384 tokens** 时生成一个子块，直接复用原完整文本。
- 超过 384 tokens 时按段落生成子块，目标 **256 tokens**；过长普通段落再按句子边界拆分。Markdown 表格、列表段落和不可再分的句子保持完整，允许超过目标值；编码器的 8192-token 硬上限仍会检查，超限报错。
- 子块增加规则标题路径；有地形上下文时保留地形名称。无固定 overlap，因为检索返回完整父块；子块记录父文本哈希、准确字符区间和涉及页码。
- 来源中的 `text_span` 是子块内区间，`parent_text_span` 是原父文本内区间；原始 Markdown 来源保持**原来源片段粒度**，不把清洗后的字符位置伪装成 PDF/Markdown 精确位置。原来源哈希仍用于核验完整来源片段。
- Chroma 只存子块向量，并在每条子块 metadata 中保存完整父规则。使用独立 `core_rules_qwen_parent_child_<语料哈希>_<模型指纹>` 集合；向量为 Qwen 的 768 维归一化结果。文本完全一致且源文件、模型配置均验证通过时复用已有 Qwen 向量，只实际编码新增文本。
- 检索按子块相似度取候选，按父块去重，使用最佳子块分数排序；不足 top-k 时扩大候选池。返回完整父规则及原有示例关联证据。评测的 top-k 和 MRR 按**去重后的父块**计算，避免多个子块占据名额。

缓存已存在时可离线执行：

```bash
HF_HUB_OFFLINE=1 uv run --locked --extra qwen --extra chroma python scripts/embed_parent_child.py
HF_HUB_OFFLINE=1 uv run --locked --extra qwen --extra chroma python scripts/embed_parent_child.py --query "How can I resolve multiple attacks using fast dice rolling?" --top-k 3
HF_HUB_OFFLINE=1 uv run --locked --extra qwen --extra chroma python scripts/embed_parent_child.py --evaluate --top-k 5
```

首次无模型缓存时去掉 `HF_HUB_OFFLINE=1` 下载模型。构建、查询、评测报告分别保存为 `storage/parent_child/build.json`、`query.json`、`evaluation.json`。这是分块实验，现有 18 题不能充分覆盖全部长规则，不能仅凭该评测宣称新策略更好。

本次实际构建：228 个父块、237 个子块，拆分了 5 个长规则；复用 223 条经校验的基线向量，新编码 14 条子块。18 题 Top-5 对照结果：基线与父子块方案的 hit_rate 均为 1.0、MRR 均为 0.8889、evidence_hit_rate 均为 1.0，逐题目标父块排名一致。另用快速掷骰问题确认命中局部子块后返回完整父规则。详细对照报告在 `storage/parent_child/comparison.json`。

## PDF RAG 问答闭环：Qwen + Chroma + Gemini

入口 `scripts/ask_rules.py` 使用 `config/rag.json`：Qwen 编码原问题 → 检索父子块 Chroma 集合 → 按父规则去重 → 补齐示例关联主规则 → Gemini 根据证据生成答案 → 校验引用 → 输出答案及 PDF 物理页码。默认使用父子块实验索引，top-k=5；无需重新 embedding。

```bash
uv sync --locked --extra qwen --extra chroma --extra gemini
# 在已忽略的 .env 中填写 GEMINI_API_KEY；已有配置可继续使用
# 默认仅使用本地 Qwen 缓存，必须先完成父子块索引构建
uv run --locked --extra qwen --extra chroma --extra gemini python scripts/ask_rules.py \
  --question "How close must models in a unit stay to one another?"

# 中文问题也可以直接输入；保留英文规则术语有助于检索
uv run --locked --extra qwen --extra chroma --extra gemini python scripts/ask_rules.py \
  --question "飞机在 Movement phase 中可以转向几次？" --top-k 5

# 真实本地检索，不调用 Gemini、不需要 API key
uv run --locked --extra qwen --extra chroma --extra gemini python scripts/ask_rules.py \
  --question "How can I resolve multiple attacks using fast dice rolling?" --retrieve-only

# 完整 JSON 包含答案、证据、引用、token 用量及耗时
uv run --locked --extra qwen --extra chroma --extra gemini python scripts/ask_rules.py \
  --question "Can Assault weapons shoot after advancing?" --json
```

Gemini 生成模型默认 `gemini-3.8-flash`，独立于 embedding 模型；通过 `config/rag.json` 的 `generation.model` 或 `--model` 切换。使用官方 `google-genai` SDK 的 `generate_content` 和 JSON schema；本地严格验证返回字段。[官方生成接口](https://ai.google.dev/api/generate-content)、[结构化输出](https://ai.google.dev/gemini-api/docs/structured-output)。模型可用性与配额以当前 API 账户为准。

生成要求：只依据检索证据，保留前提、限制和例外；默认中文解释、保留英文规则名；证据不足时说明缺少的信息。证据文本作为资料处理。答案正文使用 `[S1]` 等编号，程序验证编号存在、正文与 citations 数组一致；标题、来源与页码由本地 metadata 填入。页码是 **PDF 物理页、从 1 开始**，不是模型生成的页码。

`max_context_bytes=32000` 是发送的证据 JSON 的 **UTF-8 字节预算，不是 Gemini token 数**；问题由独立的 `max_question_chars=4000` 控制。超预算时跳过整个低排名规则，示例与主规则作为一个完整组合，禁止截断规则或只保留示例。没有可用完整证据时返回证据不足，不调用生成 API。此规则不会用相似度分数自动判断问题可回答，仍依赖生成模型与后续回答评测。

Qwen 默认 `qwen_local_files_only=true`，模型缓存不存在时应先构建 embedding，或显式改为 false 允许下载。生成请求仍需要联网。SDK 超时默认 60 秒、最多 3 次尝试；失败不发布答案，保存检索诊断。空输出、截断、非 JSON、非法引用都会拒绝。运行记录在已忽略的 `storage/rag/`，包含原问题、检索排名、完整证据与来源、模型、引用、实际 token 用量和耗时；API key 不写入记录。

引用校验只能证明编号和来源对应，**不能自动证明每个结论被证据支持**。现有 18 题仍是检索评测；回答的规则正确性、例外完整性和证据不足判断需要单独评测。部分 PDF 页尚未人工复核，来源记录保留 review_status。当前闭环读取 PDF 的已解析文本和表格；图示理解、自动持久化对话会话和 LangGraph 编排留待后续实现；对话问句重写与重排的配置见下文。

## 对话问句重写、子问题检索与重排

默认开启 `config/rag.json` 中的 `rewrite` 和 `rerank`。这两步复用生成配置中的 Gemini 模型和 API key；无需下载额外 reranker，也无需重建 Qwen/Chroma 索引。

流程：原问题 + 必要的对话历史 → 英文独立问题与最多 3 个检索子问题 → 原问题/独立问题/子问题分别做 Qwen 检索 → 父规则去重并按 Reciprocal Rank Fusion（RRF）合并 → Gemini 对完整父规则重排 → Top-5 完整证据 → 带引用回答。

- 重写自动触发：提供了历史，或英文问题包含 `and`、`both`、`compare`、`versus`、`vs`、`difference`，或包含多个问句。简单单轮问题跳过重写；这是轻量触发规则，不是可靠的语义分类器。
- 原问题始终参与检索；改写只补全历史指代、保留原条件，不补充未知单位类型、阶段或距离。对话历史只用于理解问题，过去的 assistant 回答不能作为规则证据。未加入中文翻译/术语转换逻辑。
- 每路默认取 15 个去重父规则，RRF 使用 `1/(60+rank)` 合并，最多保留 20 个候选。不同检索问题的 cosine 分数不直接相加。
- 重排使用 Gemini 一次返回所有候选 ID 的相关性顺序，程序验证 ID 集合和唯一性；重排完整父规则，示例附带主规则文本。输入文档字节预算为 64000，超预算规则不截断、保留在已重排候选之后的 RRF 顺序。最后选 `top_k`，再补齐关联证据。
- 重写失败回退原问题，重排失败回退 RRF 顺序；运行记录会明确标记 `fallback_original` / `fallback_fusion`。引用校验和完整证据预算继续生效。

历史文件为只包含过去消息的 JSON 数组，每条消息使用 `role`（user/assistant）和 `content`。最新问题单独通过 `--question` 传入。默认最多使用最近 6 条历史消息；输入历史总长度超过 12000 字符会报错。可用示例：

```bash
uv run --locked --extra qwen --extra chroma --extra gemini python scripts/ask_rules.py \
  --question "What about Aircraft?" --history config/rag_history.example.json

# 不带历史的复合问题可以拆成检索子问题
uv run --locked --extra qwen --extra chroma --extra gemini python scripts/ask_rules.py \
  --question "Can a unit shoot after Advancing, and can it charge after Advancing?" --json

# 对照开关：恢复原问题检索，不重写、不重排
uv run --locked --extra qwen --extra chroma --extra gemini python scripts/ask_rules.py \
  --question "Can a unit shoot after Advancing?" --no-rewrite --no-rerank
```

`--retrieve-only` 始终保持纯本地：不调用 Gemini，跳过重写和重排。完整运行记录额外包含采用的历史、query_plan、各查询对应的父规则排名、RRF 候选、重排前后顺序，以及重写/重排的状态、token 用量和耗时。最终生成同时看到原问题、独立问题和用于指代消解的历史，不把重写结果或历史回答当作新的规则事实。

启用重排会增加一次 Gemini 请求；触发重写时再增加一次请求和多路本地检索。候选顺序只是模型判断，不是校准的相关性概率。应使用开关在相同问题、相同语料上对照答案质量、排名、token 用量和延迟，不能仅凭接入重排就断言检索效果更好。

真实验证示例：历史问题为 `Can Infantry shoot after Advancing, and can they charge after Advancing?`，最新问题为 `What about Aircraft?`；重写得到 `Can Aircraft shoot after Advancing, and can they charge after Advancing?`，再拆成射击与冲锋两个子问题，保留原问题共同检索。已通过真实 Gemini 调用验证 20 个父规则重排及最终来源引用。验证摘要保存在 `storage/rag/refinement_validation.json`；测试期间也验证了服务端错误的回退和非法引用的拒绝。最终答案支持将 `[S1, S2]` 规范成 `[S1] [S2]`，不存在的来源和引用数组不一致仍会拒绝。

## SQL 只读基础层

`src/warhammer_agent/sql/` 提供 Text-to-SQL 使用的 schema、查询计划、Gemini SQL 生成与安全执行边界。`schema.py` 只读取表名和字段，根据问题中的明确关键词选择相关表与可用关联；`planner.py` 将模型返回的 JSON 解析为固定查询计划，并核对其中的表、字段、关联和过滤操作；`generator.py` 先生成结构化计划，再要求 Gemini 返回 SQL 与参数，并在本地复核表、字段和占位符；`safety.py` 使用 SQLGlot 的 SQLite AST 解析，要求单条 `SELECT` 或 `WITH ... SELECT`，并校验允许的表和函数；`database.py` 叠加 SQLite `mode=ro`、`query_only`、authorizer、执行超时和最大返回行数；`retriever.py` 按顺序调用这些组件，遇到歧义时停止执行并返回澄清问题。

```text
src/warhammer_agent/sql/
├── __init__.py       # 对外公开 schema、验证与只读数据库接口
├── schema.py         # 读取 SQLite schema 并筛选与问题相关的表
├── planner.py        # 解析并验证结构化查询计划
├── generator.py      # Gemini SQL 生成与本地结果校验
├── safety.py         # AST 验证、表/函数白名单与危险操作拒绝
├── database.py       # SQLite 只读连接、执行超时与结果行数限制
├── retriever.py      # schema → plan → SQL → 只读执行流程
└── cli.py            # SQL Retriever 命令行入口

tests/
├── unit/test_sql_generator.py       # SQL 生成结果与 Gemini 请求测试
├── unit/test_sql_planner.py         # 结构化查询计划单元测试
├── unit/test_sql_safety.py          # SQL 验证单元测试
├── integration/test_sql_database.py # SQLite 只读执行集成测试
├── integration/test_sql_schema.py   # schema 读取和筛选集成测试
└── integration/test_sql_retriever.py # SQL Retriever 流程测试
```

```python
from warhammer_agent.sql import ReadOnlyDatabase

database = ReadOnlyDatabase("data/wahadb.sqlite", max_rows=100, timeout=2)
result = database.execute(
    """
    SELECT d.name AS unit, m.name AS model, m.t AS toughness
    FROM datasheets AS d
    JOIN datasheets_models AS m ON d.Id = m.DatasheetId
    WHERE lower(d.name) LIKE ?
    """,
    ("%intercessor%",),
)
```

数据库文件继续由 `.gitignore` 排除。Gemini 设置位于 `config/sql.json`，当前模型是 `gemini-3-flash-preview`，复用 `.env` 中的 `GEMINI_API_KEY`。完整流程会调用 Gemini 两次：先生成查询计划，再生成 SQL。SQL 生成提示包含数值过滤、阵营关联和聚合计数三个 Few-Shot 示例；示例只说明 SQLite 查询结构，当前问题仍受已验证查询计划、schema 和参数约束。当前不自动修复失败结果。

```bash
# 只检查会选择哪些表，不调用 Gemini
uv run --locked python scripts/ask_database.py \
  --question "Which unit models have toughness 6?" --schema-only

# 完整查询计划、SQL 生成和只读执行
uv run --locked --extra gemini python scripts/ask_database.py \
  --question "Which unit models have toughness 6?"

# API 调试：15 秒超时且不重试，并在 stderr 显示当前阶段
uv run --locked --extra gemini python scripts/ask_database.py \
  --question "Which unit models have toughness 6?" \
  --timeout-ms 15000 --attempts 1
```

### SQL Retriever 验证

按以下顺序测试。前两步完全本地运行，不消耗 Gemini API 配额。

```bash
# 1. SQL 单元测试与集成测试
uv run --locked --extra gemini python -m pytest -q \
  tests/unit/test_sql_*.py tests/integration/test_sql_*.py

# 2. 检查三表 schema 选择，不调用 Gemini
uv run --locked --extra gemini python scripts/ask_database.py \
  --question "Which Adeptus Custodes unit models have toughness 6?" \
  --schema-only
```

第二步应选择 `datasheets_models`、`datasheets` 和 `factions`，并提供 `factions.Id = datasheets.factionId` 与 `datasheets.Id = datasheets_models.DatasheetId` 两条关联。

额度可用时，分别验证多条件过滤、三表关联和聚合计数：

```bash
uv run --locked --extra gemini python scripts/ask_database.py \
  --question "Which stratagems cost 1 CP and can be used in the Shooting phase?"

uv run --locked --extra gemini python scripts/ask_database.py \
  --question "Which Adeptus Custodes unit models have toughness 6?"

uv run --locked --extra gemini python scripts/ask_database.py \
  --question "How many unit models have toughness 6?"
```

完整查询成功时依次显示查询计划、SQL 生成、本地验证和只读执行四个阶段，最终 JSON 的 `status` 为 `executed`。每个完整问题调用 Gemini 两次；若返回 `ClientError (429)`，表示当前 API key 的生成额度已用完，应等待错误中给出的恢复时间后再试。
