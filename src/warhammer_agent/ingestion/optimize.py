"""Source-checked rule associations and conservative noise removal."""

import hashlib
import json
import re
from collections import Counter
from copy import deepcopy


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_record(block: dict, start: int, end: int) -> dict:
    raw = block["_markdown"][start:end]
    return {
        "source_block_id": block["block_id"],
        "page_number": block["page_number"],
        "selected_markdown_sha256": block["selected_markdown_sha256"],
        "markdown_span": {
            "start": block["markdown_span"]["start"] + start,
            "end": block["markdown_span"]["start"] + end,
            "unit": "unicode_character",
        },
        "source_fragment_sha256": digest(raw.encode()),
        "review_status": block["review_status"],
        "origin": block["origin"],
        **{
            k: block[k]
            for k in ["correction_path", "correction_sha256", "audit_sha256", "handler"]
            if k in block
        },
    }


def find_block(blocks: list[dict], selector: dict) -> dict:
    matches = [b for b in blocks if b["block_id"] == selector["block_id"]]
    if len(matches) != 1:
        raise ValueError(
            f"Missing or ambiguous relation source: {selector['block_id']}"
        )
    block = matches[0]
    if (
        block["page_number"] != selector["page_number"]
        or block["section_title"] != selector["section_title"]
        or block["text_sha256"] != selector["text_sha256"]
    ):
        raise ValueError(f"Relation source changed; review {selector['block_id']}")
    return block


def only_structure(raw: str) -> bool:
    """Only headings and image references: never treat arbitrary numbers as noise."""
    body = re.sub(r"^#{1,6}\s+.*$", "", raw, flags=re.MULTILINE)
    body = re.sub(r"^!\[[^\]]*\]\([^)]+\)\s*$", "", body, flags=re.MULTILINE)
    return not body.strip()


def clean_pieces(
    block: dict, noise: dict | None, drop: dict | None, audit: list[dict]
) -> list[dict]:
    raw = block["_markdown"]
    if drop:
        if block["text"].strip() != drop["text"]:
            raise ValueError("Preamble differs from reviewed exclusion")
        audit.append({**source_record(block, 0, len(raw)), "reason": drop["reason"]})
        return []
    allowed = Counter(noise["lines"]) if noise else Counter()
    removed = Counter()
    pieces = []
    start = 0
    offset = 0
    for line in raw.splitlines(keepends=True):
        # Standalone uncaptioned image markers carry no text evidence. Curated
        # image links are retained unless the whole block lacks rule/caption text.
        placeholder = line.strip() == "<!-- image -->"
        furniture = line.rstrip("\r\n") in allowed
        if placeholder or furniture:
            if offset > start:
                pieces.append({"owner": block, "start": start, "end": offset})
            end = offset + len(line)
            reason = "Uncaptioned image placeholder" if placeholder else noise["reason"]
            audit.append({**source_record(block, offset, end), "reason": reason})
            if furniture:
                removed[line.rstrip("\r\n")] += 1
            start = end
        offset += len(line)
    if offset > start:
        pieces.append({"owner": block, "start": start, "end": offset})
    if removed != allowed:
        raise ValueError(f"Noise labels changed: {block['block_id']}")
    retained = "".join(raw[p["start"] : p["end"]] for p in pieces)
    if only_structure(retained):
        audit.append(
            {
                **source_record(block, 0, len(raw)),
                "reason": "Heading-only or image-only block without textual rule evidence",
                "whole_block": True,
            }
        )
        return []
    return pieces


def optimize_blocks(blocks: list[dict], config: dict, config_hash: str) -> list[dict]:
    """Every retained fragment keeps its own page, exact raw span and review state."""
    from .corpus import text_only

    if config["schema_version"] != 1 or any(
        b["source_hash"] != config["source_sha256"]
        or b["document_sha256"] != config["document_sha256"]
        for b in blocks
    ):
        raise ValueError(
            "Corpus association configuration does not match source hashes"
        )
    # Validate all selectors before any mutation, including sources that will be
    # consumed by a merge. Do not silently skip a rule after a source changes.
    for rule in config["merge_rules"]:
        find_block(blocks, rule["target"])
        for source in rule["sources"]:
            find_block(blocks, source)
    for rule in config["move_suffix_rules"]:
        source = find_block(blocks, rule["source"])
        find_block(blocks, rule["target"])
        if source["_markdown"].count(rule["anchor"]) != 1:
            raise ValueError("Figure association anchor missing or duplicated")
    noise_map, drops = {}, {}
    for rule in config["noise_lines"]:
        identity = find_block(blocks, rule["selector"])["block_id"]
        if identity in noise_map:
            raise ValueError("Duplicate noise selector")
        noise_map[identity] = rule
    for rule in config["drop_preambles"]:
        identity = find_block(blocks, rule["selector"])["block_id"]
        if identity in drops:
            raise ValueError("Duplicate preamble exclusion")
        drops[identity] = rule
    exclusions = []
    entries = {}
    for block in blocks:
        pieces = clean_pieces(
            block,
            noise_map.get(block["block_id"]),
            drops.get(block["block_id"]),
            exclusions,
        )
        if pieces:
            entries[block["block_id"]] = {
                "base": block,
                "pieces": pieces,
                "associations": [],
            }
    # Move only the reviewed image-and-caption suffix, not the charge/fight rule.
    for rule in config["move_suffix_rules"]:
        source = entries[rule["source"]["block_id"]]
        target = entries[rule["target"]["block_id"]]
        split = source["base"]["_markdown"].index(rule["anchor"])
        before, after = [], []
        for piece in source["pieces"]:
            if piece["start"] < split:
                before.append({**piece, "end": min(piece["end"], split)})
            if piece["end"] > split:
                after.append({**piece, "start": max(piece["start"], split)})
        if not before or not after:
            raise ValueError("Empty source or figure in reviewed suffix association")
        source["pieces"] = before
        target["pieces"].extend(after)
        event = {
            "id": rule["id"],
            "kind": "move_figure_suffix",
            "reason": rule["reason"],
        }
        source["associations"].append(event)
        target["associations"].append(event)
    for rule in config["merge_rules"]:
        target = entries[rule["target"]["block_id"]]
        for selector in rule["sources"]:
            identity = selector["block_id"]
            if identity == rule["target"]["block_id"] or identity not in entries:
                raise ValueError("Conflicting or empty rule association")
            source = entries.pop(identity)
            target["pieces"].extend(source["pieces"])
            target["associations"].extend(source["associations"])
        target["associations"].append(
            {"id": rule["id"], "kind": "merge_rule", "reason": rule["reason"]}
        )
    result = []
    for entry in entries.values():
        base = entry["base"]
        text, segments, assets = "", [], []
        for piece in entry["pieces"]:
            owner = piece["owner"]
            raw = owner["_markdown"][piece["start"] : piece["end"]]
            rendered = text_only(raw, owner["page_number"]).strip("\n")
            if not rendered.strip():
                continue
            # Join a real split sentence (e.g. p34 -> p35); otherwise retain
            # paragraph boundaries and all headings/table rows.
            separator = ""
            if text:
                separator = (
                    " "
                    if (
                        not re.search(r"[.!?:;|]$", text.rstrip())
                        and re.match(r"[a-z]", rendered)
                    )
                    else "\n\n"
                )
            start = len(text) + len(separator)
            text += separator + rendered
            segments.append(
                {
                    **source_record(owner, piece["start"], piece["end"]),
                    "text_span": {
                        "start": start,
                        "end": len(text),
                        "unit": "unicode_character",
                    },
                    "rendered_text_sha256": digest(rendered.encode()),
                    "rendering": "text_only_trim_newlines",
                }
            )
            alts = {m[0] for m in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", raw)}
            for asset in owner["assets"]:
                if asset["alt"] in alts and asset not in assets:
                    assets.append(deepcopy(asset))
        if not segments:
            raise ValueError(
                "Optimization unexpectedly removed every fragment of a retained rule"
            )
        pages = sorted({s["page_number"] for s in segments})
        states = {s["review_status"] for s in segments}
        origins = {s["origin"] for s in segments}
        source_ids = list(dict.fromkeys(s["source_block_id"] for s in segments))
        identity = json.dumps(
            {
                "source_hash": base["source_hash"],
                "segments": segments,
                "text": text,
                "relations_sha256": config_hash,
            },
            sort_keys=True,
        )
        # Per-page lineage now belongs exclusively to the source segments.
        excluded_fields = {
            "_markdown",
            "markdown_span",
            "selected_markdown_sha256",
            "correction_path",
            "correction_sha256",
            "audit_sha256",
            "handler",
            "txt_span",
            "txt_sha256",
        }
        output = {k: v for k, v in base.items() if k not in excluded_fields}
        prefix = base["embedding_text"][: -len(base["text"])] if base["text"] else ""
        warnings = list(
            dict.fromkeys(
                w for piece in entry["pieces"] for w in piece["owner"]["warnings"]
            )
        )
        table = bool(re.search(r"^\s*\|.*\|\s*$", text, flags=re.MULTILINE))
        output.update(
            schema_version=3,
            block_id="core_rules.rule_" + digest(identity.encode())[:24],
            page_number=pages[0],
            page_numbers=pages,
            source_segments=segments,
            source_block_ids=source_ids,
            text=text,
            embedding_text=prefix + text,
            text_sha256=digest(text.encode()),
            assets=assets,
            warnings=warnings,
            review_status=next(iter(states))
            if len(states) == 1
            else "partially_reviewed",
            origin=next(iter(origins)) if len(origins) == 1 else "mixed",
            content_type="mixed"
            if table and assets
            else "table"
            if table
            else "figure"
            if assets
            else "text",
            associations=entry["associations"],
            relations_path="config/corpus_relations.json",
            relations_sha256=config_hash,
        )
        result.append(output)
    if not result:
        raise ValueError("No substantive rule blocks remain")
    retained_sources = {s for b in result for s in b["source_block_ids"]}
    result[0]["corpus_audit"] = {
        "input_blocks": len(blocks),
        "output_blocks": len(result),
        "dropped_blocks": [
            b["block_id"] for b in blocks if b["block_id"] not in retained_sources
        ],
        "exclusions": exclusions,
        "relations_sha256": config_hash,
        "note": "Exclusions and exact source spans are audit metadata, never embedding input.",
    }
    return result
