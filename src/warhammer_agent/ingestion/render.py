"""Recover disposable page exports from the immutable Docling snapshot."""

from pathlib import Path


def raw_page_markdown(document: Path, number: int) -> str:
    from docling_core.types.doc import DoclingDocument

    return DoclingDocument.load_from_json(document).export_to_markdown(
        page_no=number, traverse_pictures=True
    )
