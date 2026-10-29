# Local course data

Place the two course-provided source files in this directory before running the
complete application:

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
- `core_rules.docling.json` is already versioned in Git and supports
  reproducible corpus rebuilding.

The PDF and SQLite database are ignored by Git because they are local
course-provided inputs. They are never uploaded by the application. After
placing them, start commands from the repository root so relative paths resolve
consistently.
