# Course data

The course-provided source files are versioned in this directory, so the
complete application has its inputs immediately after cloning:

```text
data/
├── Core Rules.pdf             # Warhammer 40,000 Core Rules source
├── wahadb.sqlite              # Warhammer unit datasheet database
└── core_rules.docling.json    # Versioned PDF parsing snapshot
```

Keep the exact filenames and capitalisation shown above.

- `Core Rules.pdf` provides the original pages used by PDF citations and the
  optional source-page previews in the Streamlit interface.
- `wahadb.sqlite` is opened read-only by the SQL Retriever.
- `core_rules.docling.json` is the versioned Docling parsing snapshot used for
  reproducible corpus rebuilding.

Start commands from the repository root so relative paths resolve consistently.
The application reads these files locally and never modifies or uploads them at
runtime.
