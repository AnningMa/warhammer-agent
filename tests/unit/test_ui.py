from warhammer_agent.ui import citation_label, error_label


def test_citation_labels_cover_pdf_and_sql_sources():
    pdf = citation_label(
        {
            "citation_id": "S1",
            "kind": "pdf",
            "source": "Core Rules.pdf",
            "section_title": "GRENADE",
            "page_numbers": [42],
        }
    )
    sql = citation_label(
        {
            "citation_id": "S2",
            "kind": "sql",
            "database_path": "data/wahadb.sqlite",
            "schema_tables": ["datasheets", "datasheets_models"],
        }
    )

    assert pdf == "[S1] Core Rules.pdf · GRENADE · PDF physical pages 42"
    assert sql == ("[S2] data/wahadb.sqlite · tables datasheets, datasheets_models")


def test_error_label_keeps_safe_diagnostic_fields():
    error = {
        "stage": "route",
        "error_type": "ClientError",
        "api_error": {"code": 429, "message": "provider detail"},
    }

    assert error_label(error) == "route: ClientError (API 429)"
