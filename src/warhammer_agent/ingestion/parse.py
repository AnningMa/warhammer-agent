"""Parse a source PDF into the immutable Docling input for corpus rebuilding."""

import argparse
from pathlib import Path


def main() -> None:
    from docling.datamodel.accelerator_options import (
        AcceleratorDevice,
        AcceleratorOptions,
    )
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("data/core_rules.docling.json")
    )
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        accelerator_options=AcceleratorOptions(
            device=AcceleratorDevice.CPU, num_threads=args.threads
        ),
    )
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
        }
    )
    result = converter.convert(args.pdf)
    if result.status.value != "success" or result.errors:
        raise RuntimeError(
            f"PDF conversion incomplete: {result.status.value}; {result.errors}"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.document.save_as_json(args.output)
    print(f"Parsed {len(result.document.pages)} pages into {args.output}")


if __name__ == "__main__":
    main()
