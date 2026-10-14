"""Attach verified terrain context and explicit example-to-rule relationships."""

from copy import deepcopy

from .corpus import digest


def select(blocks: list[dict], selector: dict) -> dict:
    matches = [
        b
        for b in blocks
        if selector["source_block_id"] in b["source_block_ids"]
        and b["page_number"] == selector["page_number"]
        and b["section_title"] == selector["section_title"]
    ]
    if len(matches) != 1 or matches[0]["text_sha256"] != selector["text_sha256"]:
        raise ValueError(
            "Rule context source changed or is ambiguous; review configuration"
        )
    return matches[0]


def enrich_blocks(blocks: list[dict], config: dict, config_hash: str) -> list[dict]:
    if config["schema_version"] != 1 or any(
        b["source_hash"] != config["source_sha256"]
        or b["document_sha256"] != config["document_sha256"]
        for b in blocks
    ):
        raise ValueError("Rule context configuration does not match corpus sources")
    result = deepcopy(blocks)
    selected = []
    used = set()
    for group in config["terrain_groups"]:
        heading = select(result, group["heading"])
        if heading["section_title"] != group["terrain"]:
            raise ValueError("Terrain name must match the verified source heading")
        targets = [select(result, s) for s in group["blocks"]]
        if heading not in targets or any(
            b["page_numbers"] != heading["page_numbers"] for b in targets
        ):
            raise ValueError("Terrain scope does not match its source page")
        for block in targets:
            if block["block_id"] in used:
                raise ValueError("Overlapping terrain contexts")
            used.add(block["block_id"])
        selected.append((group, heading, targets))
    links = [
        (select(result, r["example"]), select(result, r["parent"]), r["reason"])
        for r in config["example_links"]
    ]
    # Keep original rule text and all source spans unchanged; context is an
    # explicit derived field, grounded in an existing source heading.
    for group, heading, targets in selected:
        for block in targets:
            terrain = group["terrain"]
            block["embedding_context"] = {
                "terrain": terrain,
                "rule": block["section_title"],
            }
            block["embedding_text"] = (
                f"Terrain: {terrain}\nRule: {block['section_title']}\n\n"
                + block["text"]
            )
            if block["section_path"][0] != terrain:
                block["section_path"].insert(0, terrain)
            block["heading_context"] = "\n".join(
                "#" * (i + 1) + " " + h for i, h in enumerate(block["section_path"])
            )
            block["block_id"] = (
                "core_rules.context_"
                + digest(
                    (block["block_id"] + config_hash + block["embedding_text"]).encode()
                )[:24]
            )
        for block in targets:
            block["context_provenance"] = {
                "kind": "terrain_heading",
                "heading_block_id": heading["block_id"],
                "heading_text": terrain,
                "page_numbers": heading["page_numbers"],
                "source_segments": deepcopy(heading["source_segments"]),
                "config_path": "config/rule_context.json",
                "config_sha256": config_hash,
            }
    for example, parent, reason in links:
        if example is parent or parent.get("parent_rule_id"):
            raise ValueError("Example links must point directly to a main rule")
        if example.get("parent_rule_id"):
            raise ValueError("An example cannot have multiple parent rules")
        example["parent_rule_id"] = parent["block_id"]
        example["relationship"] = "illustrates"
        example["relationship_provenance"] = {
            "parent_source_block_ids": parent["source_block_ids"],
            "reason": reason,
            "config_path": "config/rule_context.json",
            "config_sha256": config_hash,
        }
        parent.setdefault("example_block_ids", []).append(example["block_id"])
    result[0]["corpus_audit"]["context_config_sha256"] = config_hash
    return result
