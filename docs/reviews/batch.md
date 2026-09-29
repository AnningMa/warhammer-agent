# 本轮清洗检查记录

第 21 页的未完成验证已完成；新增指定的 12 页修正。全部依据当前 PDF 原图与原始 Docling 节点进行。

| 页码 | 调整 | 结果 |
|---|---|---|
| 21 | 步骤层级与致伤表 | MAKING ATTACKS 为一级标题；五步流程与编号合并；补全原图确认的 2+/3+/4+/5+/6+，保留原表图片。 [查看页面](../../reports/cleaned/page_021.html) |
| 24 | 快速掷骰图解 | 完整图解与六步说明绑定；原始数值和投骰过程保留。 [查看页面](../../reports/cleaned/page_024.html) |
| 27 | 武器名称与图片 | 保留整页总览，另提供 13 个名称对应的局部图；没有补写武器属性。 [查看页面](../../reports/cleaned/page_027.html) |
| 29 | 冲锋流程编号 | 五个步骤合并编号；主标题与规则标题分级，Charge Bonus 单独保存。 [查看页面](../../reports/cleaned/page_029.html) |
| 30 | 地形冲锋与飞行冲锋 | 两幅图分别绑定对应规则和完整说明，图内距离不再零散列出。 [查看页面](../../reports/cleaned/page_030.html) |
| 33 | 战斗流程编号 | 三步流程合并编号，第二步下的 Select weapon / Select targets / Make attacks 保持为子流程。 [查看页面](../../reports/cleaned/page_033.html) |
| 36 | 战斗示例 A/B/C | A/B 对照保留在同一图中，C 单独成图；断行说明合并并按图归属。 [查看页面](../../reports/cleaned/page_036.html) |
| 37 | 数据卡示例：图片优先 | 保留 DATASHEETS 标题、导语及两张示例卡标题和完整原图；图内示例数值不作为正式规则正文。 [查看页面](../../reports/cleaned/page_037.html) |
| 41 | CP 与策略卡关联 | COMMAND RE-ROLL 1CP、COUNTER-OFFENSIVE 2CP、EPIC CHALLENGE 1CP；正文与 WHEN/TARGET/EFFECT 归入对应卡片。 [查看页面](../../reports/cleaned/page_041.html) |
| 42 | CP 与策略卡关联 | HEROIC INTERVENTION 2CP，其余七张 1CP；完整保留 WHEN/TARGET/EFFECT/RESTRICTIONS。 [查看页面](../../reports/cleaned/page_042.html) |
| 43 | 战略预备队表格 | 拆除重复合并表头；Incursion 250、Strike Force 500、Onslaught 750；JSON 提供带页码的 retrieval_records。 [查看页面](../../reports/cleaned/page_043.html) |
| 45 | 地形标题与图片 | 两类地形各绑定一张图，MOVEMENT/VISIBILITY 等作为所属地形下级标题。 [查看页面](../../reports/cleaned/page_045.html) |
| 46 | 地形标题层级与图片 | 用户指定的两类地形标题均为一级，其余属性标题为二级，并绑定对应图片。 [查看页面](../../reports/cleaned/page_046.html) |

## 验证
- 37 个 pytest 测试通过；ruff 和新清洗脚本 mypy 检查通过。
- 每个原始文本节点均明确归入正文、图内说明、图内保留内容或带理由的排除记录。
- 已核对图像裁剪、图片链接、流程编号、卡片 CP 数值和空间归属。
- 第 43 页数值直接核对原图；第 21 页骰面数值直接核对原图。

## 保留的边界
- 第 27 页局部裁剪可能带有相邻图像边缘，整页总览保留，避免误解孤立裁剪。未推断武器统计或规则。
- 第 37 页示例统计仍在原图和审计 JSON 中；清洗正文只提供标题、导语及图像链接。
- 第 41/42 页未根据颜色额外推断回合字段；原始 WHEN 限制完整保留。没有用外部规则更新这份 PDF。
- 本次只核验指定页面，未宣称全文已经达到检索入库标准。完整 document.md 和原始 document.json 未覆盖。

## 重复执行
```bash
uv run --locked python scripts/clean_reviewed_pages.py "data/Core Rules.pdf" --rules config/reviewed_page_*.json
```
第 21 页仍使用 scripts/clean_pdf_rule_table.py 和 config/core_rules_page_021.json。
