# Portable Qwen index package

The package distributes precomputed **document** embeddings for the existing
parent-child retriever. Testers can import them into their local Chroma store
instead of embedding the corpus again. **Qwen is still required to encode user
queries.** Gemini is used for routing, refinement, SQL and answer generation.

## What is included

A ZIP contains exactly four files:

- `manifest.json`: format version, export time, source commit, model, dimensions,
  configuration fingerprint, corpus hashes, counts and payload checksums;
- `vectors.npz`: unit-normalized child vectors and their ordered IDs; loaded with
  `allow_pickle=False`;
- `parent_child_blocks.jsonl`: complete parents, children and source relationships;
- `README.txt`: setup and import instructions.

The accompanying `.zip.sha256` checks the entire archive. No model weights, API
keys, Chroma internals, conversations, checkpoints or run records are included.
The current index contains 228 parents and 237 child vectors of 768 dimensions.

## Testers: use a downloaded package

For the current package, use the latest `main` source: tag
`v0.1.0-embeddings` predates the import tool. The verified ZIP is linked in
[README](../README.md#option-a-download-embeddings), and its checksum is included
in `docs/releases/warhammer-qwen-parent-child-index-20261030.zip.sha256`.
After saving the ZIP under `storage/releases/`, verify it from the project root:

```bash
(cd storage/releases && sha256sum -c ../../docs/releases/warhammer-qwen-parent-child-index-20261030.zip.sha256)
```

Use the source release paired with the package. It must contain
`scripts/index_package.py` and matching `config/` and `reports/` files. Do not edit
the embedding configuration before importing. From the project root:

```bash
uv sync --locked --extra agent --extra qwen --extra chroma --extra gemini --extra ui

# These two commands do not load Qwen or call Gemini.
.venv/bin/python scripts/index_package.py validate \
  --archive /path/to/warhammer-qwen-parent-child-index-20261030.zip
.venv/bin/python scripts/index_package.py import \
  --archive /path/to/warhammer-qwen-parent-child-index-20261030.zip
```

In the directory containing the downloaded ZIP and checksum file, verify the
published checksum with:

```bash
sha256sum -c warhammer-qwen-parent-child-index-20261030.zip.sha256
```

After returning to the project root, download/cache the Qwen model once if it is
not already installed, without rebuilding document vectors:

```bash
uv run --locked --extra qwen --extra chroma \
  python scripts/embed_parent_child.py --query "How does Deep Strike work?" --top-k 1
```

Then launch the normal application and enter your Gemini API key in the sidebar:

```bash
.venv/bin/python -m streamlit run scripts/chat_app.py
```

Import upserts the complete matching collection; repeated imports do not duplicate
records. Other model/corpus collections are untouched. `validate` performs no
Chroma writes. `--chroma-path /path/to/fresh-chroma` overrides the destination for
an isolated import check; it does not change the app's configured Chroma path.
Windows users should use the corresponding `.venv\Scripts\python.exe` command.
The existing Agent session implementation uses `fcntl` and requires a compatible
Unix environment such as Linux, macOS or WSL.

## Maintainers: prepare a release

Export reads the current complete Chroma collection. It does not run embedding,
download a model or use an API key:

```bash
.venv/bin/python scripts/index_package.py export \
  --output storage/releases/warhammer-qwen-parent-child-index-20261030.zip
```

The command also creates a `.zip.sha256` file and refuses to overwrite an existing
ZIP. Use a new version/date for a new package. The current format supports Qwen
parent-child collections only; it cannot convert Qwen vectors into Gemini vectors.

For GitHub Release distribution:

1. Commit the export/import tool, tests and documentation to the source repository.
2. Create a tag/release containing that tool and the matching configuration/corpus.
3. Attach the ZIP and its `.zip.sha256` file as Release assets; do not add `storage/`
   to Git. List the model and setup requirements in the release description.
4. Test a fresh import before publishing. Users must download the index attachment
   separately from GitHub's automatically generated source archive.

Checksums detect accidental corruption; obtain both package and checksum from the
trusted release. ZIP members are read by exact name and never extracted as paths.
The importer rejects source/configuration mismatches, invalid vector shapes,
non-finite values, mismatched IDs/order and unsupported formats before writing.
