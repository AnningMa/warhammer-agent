> Historical commands before the ingestion refactor; see ../../README.md for current commands.

# PDF initial probe

Install dependencies with `uv sync --locked`. PyTorch and torchvision use the CPU index.

Run from the repository root:

```bash
uv run --locked python scripts/probe_pdf.py "data/Core Rules.pdf"
```

Outputs: `reports/pdf_probe/report.json` and `reports/pdf_probe/pages.csv`.
Override the directory with `--output-dir PATH`. Each run replaces these reports.

Page numbers start at 1. Native text is extracted without OCR. No-text pages
are not necessarily blank. Image counts measure displayed raster instances,
not unique assets or vector artwork. Tables are heuristic candidates. Rotation
is the PDF rotation flag, not inferred text orientation. Failed measurements
are absent in JSON and empty in CSV, with errors recorded. Check pages_with_errors
before treating aggregate counts as complete.

The probe does not run Docling conversion, OCR, or download model weights.

Validation:

```bash
uv lock --check
uv run --locked python -m pytest -q
uv run --locked ruff check scripts/probe_pdf.py tests/test_probe_pdf.py
uv run --locked mypy --follow-imports=skip --ignore-missing-imports scripts/probe_pdf.py
```


# Docling structural parsing

```bash
uv run --locked python scripts/parse_pdf.py "data/Core Rules.pdf"
```

Uses CPU (4 threads), native PDF text, layout analysis and accurate table structure
recognition. OCR is disabled for this text-bearing PDF; image-only text is not
recovered. First use downloads model weights from Hugging Face. No remote document
conversion service is enabled.

Outputs under `reports/docling/`:

- `document.md`: whole-document Markdown.
- `document.json`: Docling structure, bounding boxes and page provenance.
- `pages/page_NNN.md`: Markdown by physical PDF page (1-based).
- `quality.json`: status, settings, errors, ordered items and native token recall.

For a small experiment, use a separate output directory:

```bash
uv run --locked python scripts/parse_pdf.py "data/Core Rules.pdf" --start-page 13 --end-page 14 --output-dir reports/docling_sample
```

Outputs with the same names are overwritten. Use a fresh output directory when
changing page ranges to avoid mixing old page files with a new run.
Picture child text is included with `traverse_pictures=True` so diagram labels,
CP badges and headings classified inside pictures are not silently omitted.
Their semantic relationship to surrounding text still requires review.
Token recall is only an order-independent English word overlap diagnostic, not
an accuracy score. Missing page furniture, punctuation splitting, picture text,
and duplicated table headers affect it. Inspect page Markdown alongside the PDF;
verify rule-card grouping and table relationships before indexing.


Generate a side-by-side review of representative pages after conversion:

```bash
uv run --locked python scripts/build_pdf_review.py "data/Core Rules.pdf"
```

Open `reports/docling/review.html` in a browser. The left column shows the original
page and the right shows the extracted Markdown source. Use `--pages 6 20 59`
to select pages. Review images are local; no PDF content is uploaded.

# Reviewed page 4 cleanup

```bash
uv run --locked python scripts/clean_pdf_regions.py "data/Core Rules.pdf" --rules config/core_rules_page_004.json
uv run --locked python scripts/build_pdf_review.py "data/Core Rules.pdf" --result-dir reports/cleaned --pages 4
```

This source-specific correction extracts 11 reviewed heading/body regions from
physical PDF page 4, reading the left column before the right. The 8-point cutoff
is specific to this page: body text is 8.5 points and miniature example text is
smaller. It must not be applied globally. The source SHA-256 and expected headings
are checked before output; changed PDFs require review rather than silent reuse.

`reports/cleaned/pages/page_004.md` is the cleaned page.
`reports/cleaned/page_004.json` preserves source span coordinates, region rules and
excluded text for auditing. The raw Docling files are unchanged. This does not
rebuild the full document or preserve example illustrations in the cleaned text;
`reports/cleaned/review.html` retains the original page for visual comparison.

# Reviewed page 6 figure cleanup

```bash
uv run --locked python scripts/clean_pdf_figure.py "data/Core Rules.pdf"
```

Uses `config/core_rules_page_006.json` and the original Docling JSON. Both PDF and
Docling JSON checksums must match; changed inputs require re-review. Every text
node on this page must be assigned exactly once. This rule is specific to page 6.

Outputs under `reports/cleaned/`:
- `pages/page_006.md`: original body and summary, complete figure and A/B captions.
- `images/page_006_coherency.png`: 2x rendered figure, including labels and legend.
- `page_006.json`: figure/caption relationships, raw nodes and provenance; distances
  and diagram labels remain in `figure.annotations`, outside prose.
- `page_006.html`: viewable cleaned page with the actual figure, not a placeholder.

Page furniture is isolated. Measurements in body rules are preserved. No OCR or
inferred diagram interpretation is added. Raw Docling files and page 4 cleanup
remain unchanged; the whole-document Markdown is not rebuilt.

# Reviewed page 8 image links

```bash
uv run --locked python scripts/clean_pdf_visibility.py "data/Core Rules.pdf"
```

The source-specific mapping in `config/core_rules_page_008.json` places the four
visibility diagrams below their corresponding rule text. Crops use Docling picture
coordinates converted to top-left PDF coordinates, rendered at 2x. Embedded labels
and the Unit Visible explanation are preserved. The decorative page strip and page
footer are isolated in the audit JSON. Source PDF and Docling JSON hashes must match.

Outputs: `reports/cleaned/pages/page_008.md`, `page_008.json`, `page_008.html`,
and four `images/page_008_*.png` files. Open the HTML to view actual images; Markdown
image paths are relative to the page file. Raw Docling results and other cleaned
pages are unchanged. This is a page-specific correction, not a full-document rebuild.

# Reviewed page 9 D3 table correction

```bash
uv run --locked python scripts/clean_pdf_table.py "data/Core Rules.pdf"
```

`config/core_rules_page_009.json` records the manually verified mapping:
D6 1/2 → D3 1, D6 3/4 → D3 2, D6 5/6 → D3 3. The original table crop is retained.
Only the incomplete table and its four fragmented dice image placeholders are
replaced. Other page content is unchanged. Both source PDF and page Markdown
checksums must match; changed inputs require review. The original fragment, table
reference, crop coordinates and correction method remain in `page_009.json`.

Outputs: `reports/cleaned/pages/page_009.md`, `page_009.json`, `page_009.html`,
and `images/page_009_rolling_a_d3.png`. HTML renders the corrected image/table;
surrounding unmodified Markdown is shown as source text. No OCR is required.

# Reviewed pages 10–11 navigation and recap cleanup

```bash
uv run --locked python scripts/clean_pdf_text.py --rules config/core_rules_page_010.json
uv run --locked python scripts/clean_pdf_text.py --rules config/core_rules_page_011.json
```

Page 10 isolates detached diagram numbers and page furniture; five phases retain
explicit ordered headings. Page 11 isolates opening navigation/page numbers,
the repeated Battle-shock recap, repeated two-step sidebar and footer. Full rules,
the actual numbered steps, and GAINING COMMAND POINTS remain. These summaries were
present in the original layout, not necessarily duplicate parser detections.

Source JSON hash and complete node partition are checked. Omitted text and picture
nodes are archived in each cleaned page JSON. Outputs are page_NNN.md under pages/,
and page_NNN.html / page_NNN.json under reports/cleaned/. Raw results are unchanged.

Page 13 uses the same reviewed text cleaner:

```bash
uv run --locked python scripts/clean_pdf_text.py --rules config/core_rules_page_013.json
```

Removes detached navigation/page numbers and the repeated closing two-step sidebar.
Retains the numbered MOVE UNITS section, full movement rules, summaries, and the
transition to Reinforcements. Outputs are `reports/cleaned/pages/page_013.md`,
`page_013.html` and `page_013.json`; omissions remain auditable in JSON.

Page 14 reuses the figure cleaner with grouped caption fragments:

```bash
uv run --locked python scripts/clean_pdf_figure.py "data/Core Rules.pdf" --rules config/core_rules_page_014.json
```

A/B fragments are merged into two captions attached to the complete Desperate
Escape example. Dice outcomes (1, 2, 4, 4, 6) and the two destroyed models remain
in the caption. Diagram-only 6-inch/A/B labels remain in the image and JSON, not
standalone prose. Full movement rules and summaries remain. Outputs are
`reports/cleaned/pages/page_014.md`, `page_014.html`, `page_014.json`, and
`images/page_014_desperate_escape.png`. Original Docling output is untouched.

# Reviewed page 15: multiple diagrams

```bash
uv run --locked python scripts/clean_pdf_figures.py "data/Core Rules.pdf" --rules config/core_rules_page_015.json
```

Terrain A/B captions are joined and attached to the terrain image directly after
MOVING OVER TERRAIN. The flying example and its complete caption follow FLYING
and its summaries. Distances inside explanations remain intact; standalone image
labels stay in the images and audit JSON. All page text nodes must be accounted
for once, and source checksums must match. Outputs: `pages/page_015.md`,
`page_015.html`, `page_015.json` and two `images/page_015_*.png` under
`reports/cleaned/`. Raw parsing results are unchanged.

Page 18 uses the multi-diagram cleaner:

```bash
uv run --locked python scripts/clean_pdf_figures.py "data/Core Rules.pdf" --rules config/core_rules_page_018.json
```

Left-column rules are followed by an independent TRANSPORT EXAMPLES section:
Embarking, Disembarking, Destroyed Transports. Each example has its own image and
original caption. The original composite picture is #/pictures/37; crop coordinates
and source text refs are retained in the rule/audit JSON. Standalone measurement
labels and repeated image titles remain in the images/JSON, not detached prose.
Dice outcomes, wounds, distances and Battle-shocked status in explanatory text
remain intact. Output: reports/cleaned/pages/page_018.md, page_018.html,
page_018.json and three images/page_018_*.png files.

Page 19 hierarchy correction:

```bash
uv run --locked python scripts/clean_pdf_text.py --rules config/core_rules_page_019.json
```

SHOOTING PHASE is H1. Sidebar steps become numbered list items. Eligibility and
Select Targets are numbered H2 sections; the eligibility heading is explicitly
reused from the overview with source refs recorded. Lone Operative is an independent
H2 ability. Opening navigation digits and printed page/footer are isolated. Actual
rules and meaningful numeric values remain. Outputs: page_019.md under cleaned/pages,
and page_019.html / page_019.json under reports/cleaned.

Page 21 attack hierarchy and dice-face table correction:

```bash
uv run --locked python scripts/clean_pdf_rule_table.py "data/Core Rules.pdf" --rules config/core_rules_page_021.json
```

MAKING ATTACKS is H1; the five-step overview is an ordered list. Numbered Hit Roll
and Wound Roll remain H2. Navigation/page numbers are isolated. The original wound
roll crop and visually verified 2+/3+/4+/5+/6+ table replace the incomplete plus-only
extraction. Conditions retain the original wording/order. Source hashes, original
table node, reviewed rows and crop coordinates are recorded in page_021.json.
Outputs: reports/cleaned/pages/page_021.md, page_021.html, page_021.json, and
images/page_021_wound_roll.png. Raw Docling results are not overwritten.

# Batch of visually reviewed corrections (24–46 selected pages)

```bash
uv run --locked python scripts/clean_reviewed_pages.py "data/Core Rules.pdf" --rules config/reviewed_page_*.json
```

Selected pages: 24, 27, 29, 30, 33, 36, 37, 41, 42, 43, 45, 46. Each config is
bound to the PDF and original Docling JSON hashes. Each source text node must have
an explicit destination or an exclusion reason; originals remain untouched.
Blocks preserve source nodes and page/bbox data. Card blocks expose CP cost and
original WHEN/TARGET/EFFECT/RESTRICTIONS fields. Page 43 provides normalized
retrieval_records. Page 37 uses image-first presentation; example statistics stay
in original images and audit data rather than searchable prose.

`reports/cleaned/batch_review.html` is the review entry point;
`BATCH_REVIEW.md` documents the scope and remaining limitations. Each page has
Markdown, HTML and JSON plus any corresponding local image crops. These are
page-specific reviewed corrections, not a general automatic layout algorithm.
