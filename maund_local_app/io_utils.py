from __future__ import annotations

import csv
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from .models import BlockOverride, BlockSpec


NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
DNA_BASES = {"A", "C", "G", "T", "N"}
BLOCK_HINTS: dict[tuple[str, str], dict[str, tuple[str, ...] | str]] = {
    (
        "49~67",
        "AAATGAATCTGCTAATGAA",
    ): {
        "name": "N234",
        "desired_products": (
            "AAATGAATCTGCTGATGAA",
            "AAATGAATCTGCTAGTGAA",
        ),
    },
    (
        "74~93,95,96",
        "TTGGCCGATTGATTTTCCAATA",
    ): {
        "name": "F260",
        "desired_products": (
            "TTGGCCGATTGATTTCCCAATA",
        ),
    },
}


def col_to_idx(col_letters: str) -> int:
    out = 0
    for ch in col_letters:
        out = out * 26 + (ord(ch) - ord("A") + 1)
    return out - 1


def parse_id_spec(spec: str) -> tuple[int, ...]:
    vals: list[int] = []
    for part in spec.split(","):
        token = part.strip()
        if not token:
            continue
        sep = "-" if "-" in token else "~" if "~" in token else None
        if sep:
            start_text, end_text = token.split(sep, 1)
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise ValueError(f"Invalid range: {token}")
            vals.extend(range(start, end + 1))
            continue
        vals.append(int(token))
    return tuple(vals)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open() as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, object]], fields: Iterable[str]) -> None:
    field_list = list(fields)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=field_list, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in field_list})


def parse_xlsx_rows(xlsx_path: Path, sheet_name: str | None = None) -> list[list[str]]:
    with zipfile.ZipFile(xlsx_path) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("a:si", NS):
                shared.append("".join((t.text or "") for t in si.findall(".//a:t", NS)))

        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        sheets = workbook.findall("a:sheets/a:sheet", NS)
        chosen = None
        if sheet_name is None:
            chosen = sheets[0] if sheets else None
        else:
            for sheet in sheets:
                if sheet.attrib.get("name") == sheet_name:
                    chosen = sheet
                    break
        if chosen is None:
            raise RuntimeError(f"Sheet not found: {sheet_name or '<first>'} in {xlsx_path}")

        rid = chosen.attrib.get(REL)
        if not rid:
            raise RuntimeError(f"Sheet rid not found: {xlsx_path}")

        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_map = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
        }
        ws_target = rel_map.get(rid)
        if not ws_target:
            raise RuntimeError(f"Worksheet target missing: {xlsx_path}")
        worksheet = ET.fromstring(zf.read("xl/" + ws_target))

    rows: list[list[str]] = []
    for row in worksheet.findall("a:sheetData/a:row", NS):
        cells: dict[int, str] = {}
        max_idx = -1
        for cell in row.findall("a:c", NS):
            cref = cell.attrib.get("r", "")
            match = re.match(r"([A-Z]+)\d+", cref)
            if not match:
                continue
            cell_idx = col_to_idx(match.group(1))
            max_idx = max(max_idx, cell_idx)
            value_node = cell.find("a:v", NS)
            if value_node is None:
                cells[cell_idx] = ""
                continue
            raw = value_node.text or ""
            if cell.attrib.get("t") == "s" and raw.isdigit():
                shared_idx = int(raw)
                cells[cell_idx] = shared[shared_idx] if shared_idx < len(shared) else ""
            else:
                cells[cell_idx] = raw
        if max_idx < 0:
            rows.append([])
            continue
        values = ["" for _ in range(max_idx + 1)]
        for idx, value in cells.items():
            values[idx] = value
        rows.append(values)
    return rows


def is_dna_text(text: str) -> bool:
    seq = text.strip().upper()
    return len(seq) >= 12 and all(base in DNA_BASES for base in seq)


def normalize_id_row(row: list[str]) -> tuple[str, str, str]:
    if len(row) >= 4 and not row[0].strip() and row[1].strip():
        return row[1].strip(), row[2].strip(), row[3].strip()
    if len(row) >= 3:
        return row[0].strip(), row[1].strip(), row[2].strip()
    if len(row) == 2:
        return row[0].strip(), row[1].strip(), ""
    if len(row) == 1:
        return row[0].strip(), "", ""
    return "", "", ""


def parse_desired_products(text: str) -> tuple[str, ...]:
    products: list[str] = []
    for token in re.split(r"[\n,;/]+", text.strip()):
        seq = token.strip().upper().replace(" ", "")
        if is_dna_text(seq):
            products.append(seq)
    deduped: list[str] = []
    for seq in products:
        if seq not in deduped:
            deduped.append(seq)
    return tuple(deduped)


def slugify_name(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower())
    slug = slug.strip("_")
    return slug or "block"


def _header_is_block_start(row: list[str]) -> bool:
    return len(row) > 1 and row[1].strip().lower() == "sample id no."


def _first_nonempty(*values: str) -> str:
    for value in values:
        if value.strip():
            return value.strip()
    return ""


def _normalize_dna_sequence(text: str) -> str:
    return text.strip().upper().replace(" ", "")


def _desired_products_from_cells(cells: list[str], target_window: str) -> tuple[str, ...]:
    products: list[str] = []
    for cell in cells:
        seq = _normalize_dna_sequence(cell)
        if len(seq) == len(target_window) and seq and all(base in DNA_BASES for base in seq):
            products.append(seq)
    deduped: list[str] = []
    for seq in products:
        if seq not in deduped:
            deduped.append(seq)
    return tuple(deduped)


def _block_hint(sample_spec: str, target_window: str) -> tuple[str, tuple[str, ...]]:
    hint = BLOCK_HINTS.get((sample_spec, target_window))
    if not hint:
        return "", ()
    return str(hint.get("name", "")), tuple(hint.get("desired_products", ()))  # type: ignore[arg-type]


def apply_block_overrides(
    blocks: tuple[BlockSpec, ...],
    overrides: tuple[BlockOverride, ...] = (),
) -> tuple[BlockSpec, ...]:
    override_by_index = {item.block_index: item for item in overrides}
    resolved: list[BlockSpec] = []
    for block in blocks:
        hint_name, hint_products = _block_hint(block.sample_spec, block.target_window)
        override = override_by_index.get(block.block_index)
        block_name = block.block_name or hint_name or f"block_{block.block_index}"
        desired_products = block.desired_products or hint_products
        if override:
            if override.block_name.strip():
                block_name = override.block_name.strip()
            if override.desired_products:
                desired_products = tuple(seq.upper() for seq in override.desired_products)
        resolved.append(
            BlockSpec(
                block_index=block.block_index,
                block_name=block_name,
                sample_spec=block.sample_spec,
                full_sequence=block.full_sequence,
                target_window=block.target_window,
                row_items=block.row_items,
                desired_products=desired_products,
            )
        )
    return tuple(resolved)


def load_block_specs(
    seq_xlsx: Path,
    overrides: tuple[BlockOverride, ...] = (),
) -> tuple[BlockSpec, ...]:
    rows = parse_xlsx_rows(seq_xlsx, "Sheet1")
    blocks: list[BlockSpec] = []
    idx = 0
    while idx < len(rows):
        row = rows[idx]
        if not _header_is_block_start(row):
            idx += 1
            continue

        header_name = row[0].strip() if row and row[0].strip() else ""
        idx += 1
        while idx < len(rows) and not any(cell.strip() for cell in rows[idx]):
            idx += 1
        if idx >= len(rows):
            break

        spec_row = rows[idx]
        sample_spec = spec_row[1].strip() if len(spec_row) > 1 else ""
        full_sequence = _normalize_dna_sequence(spec_row[2]) if len(spec_row) > 2 else ""
        target_window = _normalize_dna_sequence(spec_row[3]) if len(spec_row) > 3 else ""
        block_name = _first_nonempty(header_name, spec_row[0] if spec_row else "")
        desired_products = _desired_products_from_cells(spec_row[4:], target_window) if len(spec_row) > 4 else ()
        idx += 1

        row_items: list[tuple[str, int]] = []
        while idx < len(rows):
            row = rows[idx]
            if _header_is_block_start(row):
                break
            label = row[1].strip() if len(row) > 1 else ""
            sample_text = row[2].strip() if len(row) > 2 else ""
            if label and sample_text.isdigit():
                row_items.append((label, int(sample_text)))
            idx += 1

        if sample_spec and full_sequence and target_window and row_items:
            blocks.append(
                BlockSpec(
                    block_index=len(blocks) + 1,
                    block_name=block_name,
                    sample_spec=sample_spec,
                    full_sequence=full_sequence,
                    target_window=target_window,
                    row_items=tuple(row_items),
                    desired_products=desired_products,
                )
            )

    return apply_block_overrides(tuple(blocks), overrides)


def load_seq_mappings(seq_xlsx: Path) -> dict[int, dict[str, str]]:
    mapping: dict[int, dict[str, str]] = {}
    blocks = load_block_specs(seq_xlsx)
    if blocks:
        for block in blocks:
            for sample_id in block.sample_ids:
                mapping[sample_id] = {
                    "sequence": block.full_sequence,
                    "target_window": block.target_window,
                    "block_name": block.display_name,
                }
        return mapping

    rows = parse_xlsx_rows(seq_xlsx, "Sheet1")
    for row in rows:
        sample_spec = row[1].strip() if len(row) > 1 else ""
        sequence = _normalize_dna_sequence(row[2]) if len(row) > 2 else ""
        target_window = _normalize_dna_sequence(row[3]) if len(row) > 3 else ""
        if not sample_spec or not re.search(r"\d", sample_spec):
            continue
        if not is_dna_text(sequence) or not is_dna_text(target_window):
            continue
        for sample_id in parse_id_spec(sample_spec.replace(" ", "")):
            mapping[sample_id] = {
                "sequence": sequence,
                "target_window": target_window,
                "block_name": row[0].strip() if row and row[0].strip() else "",
            }
    return mapping


def load_sample_tail_mapping(xlsx_path: Path) -> dict[int, dict[str, object]]:
    rows = parse_xlsx_rows(xlsx_path, "Sheet1")
    mapping: dict[int, dict[str, object]] = {}
    combo_pat = re.compile(r"Left(\d+)\+Right(\d+)", re.IGNORECASE)
    for row in rows:
        sid_spec, col2, col3 = normalize_id_row(row)
        if not sid_spec or not re.search(r"\d", sid_spec):
            continue
        combo = col2 if combo_pat.fullmatch(col2) else col3 if combo_pat.fullmatch(col3) else ""
        match = combo_pat.fullmatch(combo)
        if not match:
            continue
        left_idx = int(match.group(1))
        right_idx = int(match.group(2))
        for sid in parse_id_spec(sid_spec):
            mapping[sid] = {
                "sample_id": sid,
                "tail_combo": f"Left{left_idx}+Right{right_idx}",
                "left_tail_module": f"Left{left_idx}",
                "right_tail_module": f"Right{right_idx}",
                "left_tail_index": left_idx,
                "right_tail_index": right_idx,
            }
    return mapping


def load_tail_sequences(tale_array_xlsx: Path) -> tuple[dict[int, str], dict[int, str]]:
    rows = parse_xlsx_rows(tale_array_xlsx, "Target")
    left: dict[int, str] = {}
    right: dict[int, str] = {}
    for row in rows:
        if len(row) < 2:
            continue
        name = row[0].strip()
        sequence = row[1].strip().replace(" ", "")
        if not name or not sequence:
            continue
        left_match = re.match(r"N234\s+Left_(\d+)", name, re.IGNORECASE)
        right_match = re.match(r"N234\s+Right_(\d+)", name, re.IGNORECASE)
        if left_match:
            left[int(left_match.group(1))] = sequence
        if right_match:
            right[int(right_match.group(1))] = sequence
    return left, right


def target_slug(target_seq: str) -> str:
    text = re.sub(r"[^ACGTN]+", "", target_seq.upper())
    return (text[:10] or "target").lower()
