from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from .models import BlockSpec
from .reporting import _format_heatmap_scale, _format_heatmap_tick, colorize_haplotype, escape_html, heatmap_color


PRIME_CLASS_ORDER = (
    "exact_intended",
    "intended_plus_extra",
    "other_substitution_byproduct",
    "scaffold_derived",
    "indel_only",
)

PRIME_CLASS_LABELS = {
    "wt": "WT",
    "exact_intended": "Exact intended",
    "intended_plus_extra": "Intended + extra",
    "other_substitution_byproduct": "Other substitution byproduct",
    "scaffold_derived": "Scaffold-derived",
    "indel_only": "Indel only",
}

TRANS = str.maketrans("ATGCN", "TACGN")


def revcomp(seq: str) -> str:
    return seq.translate(TRANS)[::-1]


def read_counter_file(path: Path) -> Counter[str]:
    counter: Counter[str] = Counter()
    if not path.exists():
        return counter
    with path.open() as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            parts = text.split("\t")
            if len(parts) < 2:
                continue
            counter[parts[0].strip().upper()] += int(parts[1])
    return counter


def scaffold_match(sequence: str, scaffold_sequence: str) -> bool:
    motif = scaffold_sequence.strip().upper()
    if not motif:
        return False
    return motif in sequence or revcomp(motif) in sequence


def classify_prime_substitution(target: str, haplotype: str, desired_products: tuple[str, ...]) -> str:
    if haplotype == target:
        return "wt"
    if any(haplotype == desired for desired in desired_products):
        return "exact_intended"
    for desired in desired_products:
        if contains_intended_substitutions(target, haplotype, desired):
            return "intended_plus_extra"
    return "other_substitution_byproduct"


def contains_intended_substitutions(target: str, haplotype: str, desired: str) -> bool:
    if len(target) != len(haplotype) or len(target) != len(desired):
        return False
    intended_positions = [idx for idx, (ref_base, desired_base) in enumerate(zip(target, desired)) if ref_base != desired_base]
    if not intended_positions:
        return False
    return all(haplotype[idx] == desired[idx] for idx in intended_positions)


def intended_positions_map(target: str, desired_products: tuple[str, ...]) -> dict[int, str]:
    positions: dict[int, str] = {}
    for desired in desired_products:
        for idx, (ref_base, desired_base) in enumerate(zip(target, desired), start=1):
            if ref_base == desired_base:
                continue
            existing = positions.get(idx)
            if existing and existing != desired_base:
                raise ValueError(f"Conflicting intended base at position {idx}: {existing} vs {desired_base}")
            positions[idx] = desired_base
    return positions


def validate_prime_desired_products(target: str, desired_products: tuple[str, ...]) -> tuple[str, ...]:
    if not desired_products:
        raise ValueError("Desired product sequence is required for Prime Editing.")
    normalized: list[str] = []
    for desired in desired_products:
        seq = desired.strip().upper()
        if len(seq) != len(target):
            raise ValueError(f"Prime desired product must match target length: {seq}")
        if any(base not in {"A", "C", "G", "T", "N"} for base in seq):
            raise ValueError(f"Prime desired product contains non-DNA character: {seq}")
        if seq == target:
            raise ValueError(f"Prime desired product must differ from target: {seq}")
        normalized.append(seq)
    intended_positions_map(target, tuple(normalized))
    return tuple(dict.fromkeys(normalized))


def validate_prime_scaffold_sequence(scaffold_sequence: str) -> str:
    seq = scaffold_sequence.strip().upper()
    if not seq:
        return ""
    if any(base not in {"A", "C", "G", "T", "N"} for base in seq):
        raise ValueError(f"Scaffold sequence contains non-DNA character: {scaffold_sequence}")
    if len(seq) < 8:
        raise ValueError("Scaffold sequence must be at least 8 nt.")
    return seq


def build_prime_sample_reports(
    *,
    run_rows: list[dict[str, object]],
    desired_products: tuple[str, ...],
    scaffold_sequence: str,
    max_alleles_per_class: int = 8,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    per_sample_rows: list[dict[str, object]] = []
    allele_rows: list[dict[str, object]] = []
    scaffold_rows: list[dict[str, object]] = []

    for row in sorted(run_rows, key=lambda item: int(item["sample_id"])):
        if int(row["return_code"]) != 0 or not bool(row.get("same_length_exists")):
            continue

        sample_id = int(row["sample_id"])
        target = str(row["rgen"]).upper()
        target_len = len(target)
        target_start = int(row["target_index_in_fragment"])
        comparison_length = int(row["comparison_length"])
        all_counter = read_counter_file(Path(str(row["all_file"])))
        total_analyzed_reads = int(row.get("all_read_count", sum(all_counter.values())))
        same_length_total_reads = int(row.get("same_length_read_count", 0))

        class_counts = {name: 0 for name in ("wt",) + PRIME_CLASS_ORDER}
        allele_by_class: dict[str, Counter[str]] = {name: Counter() for name in PRIME_CLASS_ORDER}

        for fragment, count in all_counter.items():
            if len(fragment) == comparison_length and len(fragment) >= target_start + target_len:
                haplotype = fragment[target_start : target_start + target_len]
                if haplotype == target:
                    class_counts["wt"] += count
                    continue
                allele_class = (
                    "scaffold_derived"
                    if scaffold_match(fragment, scaffold_sequence)
                    else classify_prime_substitution(target, haplotype, desired_products)
                )
                class_counts[allele_class] += count
                allele_by_class[allele_class][haplotype] += count
                if allele_class == "scaffold_derived":
                    scaffold_rows.append(
                        {
                            "sample_id": sample_id,
                            "allele_sequence": haplotype,
                            "reads": count,
                            "allele_class": PRIME_CLASS_LABELS[allele_class],
                        }
                    )
                continue

            allele_class = "scaffold_derived" if scaffold_match(fragment, scaffold_sequence) else "indel_only"
            class_counts[allele_class] += count
            allele_by_class[allele_class][fragment] += count
            if allele_class == "scaffold_derived":
                scaffold_rows.append(
                    {
                        "sample_id": sample_id,
                        "allele_sequence": fragment,
                        "reads": count,
                        "allele_class": PRIME_CLASS_LABELS[allele_class],
                    }
                )

        def pct(value: int) -> float:
            return (value / total_analyzed_reads * 100.0) if total_analyzed_reads else 0.0

        prime_edited_total_reads = class_counts["exact_intended"] + class_counts["intended_plus_extra"]
        indel_only_reads = class_counts["indel_only"]
        altered_total = sum(class_counts[name] for name in PRIME_CLASS_ORDER)
        purity = (class_counts["exact_intended"] / altered_total * 100.0) if altered_total else 0.0
        if indel_only_reads == 0:
            edit_to_indel_ratio = "INF" if prime_edited_total_reads > 0 else ""
        else:
            edit_to_indel_ratio = f"{prime_edited_total_reads / indel_only_reads:.6f}"

        per_sample_rows.append(
            {
                "sample_id": sample_id,
                "replicate": int(row["replicate"]),
                "condition": str(row["condition"]),
                "s_index": int(row["s_index"]),
                "target_seq": target,
                "desired_products": ",".join(desired_products),
                "scaffold_sequence": scaffold_sequence,
                "total_analyzed_reads": total_analyzed_reads,
                "same_length_total_reads": same_length_total_reads,
                "wt_reads": class_counts["wt"],
                "wt_pct": f"{pct(class_counts['wt']):.6f}",
                "exact_intended_reads": class_counts["exact_intended"],
                "exact_intended_pct": f"{pct(class_counts['exact_intended']):.6f}",
                "intended_plus_extra_reads": class_counts["intended_plus_extra"],
                "intended_plus_extra_pct": f"{pct(class_counts['intended_plus_extra']):.6f}",
                "other_substitution_byproduct_reads": class_counts["other_substitution_byproduct"],
                "other_substitution_byproduct_pct": f"{pct(class_counts['other_substitution_byproduct']):.6f}",
                "scaffold_derived_reads": class_counts["scaffold_derived"],
                "scaffold_derived_pct": f"{pct(class_counts['scaffold_derived']):.6f}",
                "indel_only_reads": class_counts["indel_only"],
                "indel_only_pct": f"{pct(class_counts['indel_only']):.6f}",
                "prime_edited_total_reads": prime_edited_total_reads,
                "prime_edited_total_pct": f"{pct(prime_edited_total_reads):.6f}",
                "edit_to_indel_ratio": edit_to_indel_ratio,
                "product_purity_pct": f"{purity:.6f}",
                "all_file": str(row["all_file"]),
                "same_length_file": str(row["same_length_file"]),
            }
        )

        for allele_class in PRIME_CLASS_ORDER:
            for rank, (sequence, count) in enumerate(allele_by_class[allele_class].most_common(max_alleles_per_class), start=1):
                allele_rows.append(
                    {
                        "sample_id": sample_id,
                        "target_seq": target,
                        "allele_class": allele_class,
                        "allele_class_label": PRIME_CLASS_LABELS[allele_class],
                        "rank": rank,
                        "allele_sequence": sequence,
                        "reads": count,
                        "allele_pct": f"{pct(count):.6f}",
                        "desired_products": ",".join(desired_products),
                        "same_length": allele_class != "indel_only",
                    }
                )

    allele_rows.sort(key=lambda item: (int(item["sample_id"]), PRIME_CLASS_ORDER.index(str(item["allele_class"])), int(item["rank"])))
    return per_sample_rows, allele_rows, scaffold_rows


def build_prime_heatmap_tables(
    *,
    block: BlockSpec,
    run_rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    intended_map = intended_positions_map(block.target_window, block.desired_products)
    run_rows_by_sample = {int(row["sample_id"]): row for row in run_rows}
    column_specs: list[dict[str, object]] = []
    for idx, ref_base in enumerate(block.target_window, start=1):
        intended_base = intended_map.get(idx, "")
        column_specs.append(
            {
                "position": idx,
                "ref_base": ref_base,
                "intended_base": intended_base,
                "field": f"pos_{idx:02d}_{ref_base}",
                "is_highlighted": bool(intended_base),
            }
        )

    matrix_rows: list[dict[str, object]] = []
    detail_rows: list[dict[str, object]] = []
    for label, sample_id in block.row_items:
        row = run_rows_by_sample.get(sample_id)
        if row is None or int(row["return_code"]) != 0 or not bool(row.get("same_length_exists")):
            continue
        target_start = int(row["target_index_in_fragment"])
        total_analyzed_reads = int(row.get("all_read_count", 0))
        same_length_counter = read_counter_file(Path(str(row["same_length_file"])))
        row_label = f"{label} (sample {sample_id})"
        is_wt = "col0" in label.lower() or "wild-type" in label.lower()
        matrix_row: dict[str, object] = {
            "sample_id": sample_id,
            "row_label": row_label,
            "row_key": label,
            "is_wt": is_wt,
            "total_analyzed_reads": total_analyzed_reads,
        }
        for spec in column_specs:
            intended_base = str(spec["intended_base"])
            intended_reads = 0
            if intended_base:
                for fragment, count in same_length_counter.items():
                    haplotype = fragment[target_start : target_start + len(block.target_window)]
                    if len(haplotype) >= int(spec["position"]) and haplotype[int(spec["position"]) - 1] == intended_base:
                        intended_reads += count
            pct = (intended_reads / total_analyzed_reads * 100.0) if total_analyzed_reads else 0.0
            matrix_row[str(spec["field"])] = f"{pct:.6f}"
            detail_rows.append(
                {
                    "sample_id": sample_id,
                    "row_label": row_label,
                    "row_key": label,
                    "is_wt": is_wt,
                    "position": int(spec["position"]),
                    "ref_base": str(spec["ref_base"]),
                    "intended_base": intended_base,
                    "intended_reads": intended_reads,
                    "total_analyzed_reads": total_analyzed_reads,
                    "intended_pct": f"{pct:.6f}",
                    "is_highlighted": bool(spec["is_highlighted"]),
                }
            )
        matrix_rows.append(matrix_row)

    return matrix_rows, detail_rows, column_specs


def _render_prime_allele_tables(
    *,
    per_sample_rows: list[dict[str, object]],
    allele_rows: list[dict[str, object]],
) -> str:
    rows_by_sample: dict[int, list[dict[str, object]]] = {}
    for row in allele_rows:
        rows_by_sample.setdefault(int(row["sample_id"]), []).append(row)

    cards: list[str] = []
    for sample in per_sample_rows:
        sample_id = int(sample["sample_id"])
        target = str(sample["target_seq"]).upper()
        rows = rows_by_sample.get(sample_id, [])
        lines = [
            '<div class="card">',
            f'<div class="card-head"><div class="sid">Sample {sample_id}</div><div class="combo">Prime Editing</div></div>',
            (
                '<div class="meta">'
                f'<span>Exact intended (%): <b>{float(str(sample["exact_intended_pct"])):.4f}</b></span>'
                f'<span>Intended+extra (%): <b>{float(str(sample["intended_plus_extra_pct"])):.4f}</b></span>'
                f'<span>Indel only (%): <b>{float(str(sample["indel_only_pct"])):.4f}</b></span>'
                "</div>"
            ),
            '<div class="ref">Ref: <span class="seq">' + target + "</span></div>",
            "<table><thead><tr><th>Class</th><th>Rank</th><th>Allele</th><th>Reads</th><th>% of total</th></tr></thead><tbody>",
        ]
        if not rows:
            lines.append('<tr><td colspan="5" class="empty">No prime-editing allele found</td></tr>')
        else:
            for row in rows:
                sequence = str(row["allele_sequence"])
                if bool(row["same_length"]):
                    display = colorize_haplotype(target, sequence)
                else:
                    display = escape_html(sequence)
                lines.append(
                    f"<tr><td>{escape_html(str(row['allele_class_label']))}</td>"
                    f"<td>{int(row['rank'])}</td>"
                    f"<td><span class='seq'>{display}</span></td>"
                    f"<td>{int(row['reads'])}</td>"
                    f"<td>{float(str(row['allele_pct'])):.4f}</td></tr>"
                )
        lines.append("</tbody></table>")
        lines.append("</div>")
        cards.append("\n".join(lines))
    return "\n".join(cards)


def render_prime_html(
    *,
    title: str,
    per_sample_rows: list[dict[str, object]],
    allele_rows: list[dict[str, object]],
    scaffold_rows: list[dict[str, object]],
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cards = _render_prime_allele_tables(per_sample_rows=per_sample_rows, allele_rows=allele_rows)
    scaffold_note = (
        "<p class='note'>Scaffold-derived classification used the provided scaffold motif.</p>"
        if scaffold_rows
        else "<p class='note'>Scaffold-derived classification was not used or no scaffold-containing reads were found.</p>"
    )
    summary_rows = []
    for row in per_sample_rows:
        summary_rows.append(
            "<tr>"
            f"<td>{int(row['sample_id'])}</td>"
            f"<td>{float(str(row['wt_pct'])):.4f}</td>"
            f"<td>{float(str(row['exact_intended_pct'])):.4f}</td>"
            f"<td>{float(str(row['intended_plus_extra_pct'])):.4f}</td>"
            f"<td>{float(str(row['other_substitution_byproduct_pct'])):.4f}</td>"
            f"<td>{float(str(row['scaffold_derived_pct'])):.4f}</td>"
            f"<td>{float(str(row['indel_only_pct'])):.4f}</td>"
            f"<td>{float(str(row['prime_edited_total_pct'])):.4f}</td>"
            f"<td>{escape_html(str(row['edit_to_indel_ratio']))}</td>"
            f"<td>{float(str(row['product_purity_pct'])):.4f}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape_html(title)}</title>
  <style>
    :root {{
      --bg: #f4f1ea;
      --ink: #1d2628;
      --mut: #c33f2c;
      --card: #fffdf9;
      --line: #d6c9b8;
      --sub: #5f655f;
    }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top right, rgba(211, 179, 117, 0.18), transparent 32%),
        linear-gradient(180deg, #f7f2ea 0%, #f2ede4 100%);
      color: var(--ink);
    }}
    .wrap {{ max-width: 1520px; margin: 0 auto; padding: 24px 18px 32px; }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    h2 {{ margin: 0 0 12px; font-size: 20px; }}
    .section {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 16px; margin-bottom: 16px; }}
    .note {{ margin: 0 0 12px; color: var(--sub); font-size: 14px; line-height: 1.55; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 14px; }}
    .card {{ background: #fffdfa; border: 1px solid var(--line); border-radius: 14px; padding: 14px; }}
    .card-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: baseline; margin-bottom: 10px; }}
    .sid {{ font-size: 18px; font-weight: 700; }}
    .combo {{ color: var(--sub); font-size: 13px; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; font-size: 13px; color: var(--sub); }}
    .meta span {{ background: #f1eadc; border-radius: 999px; padding: 5px 9px; }}
    .ref {{ margin-bottom: 10px; font-size: 13px; color: var(--sub); }}
    .seq {{ font-family: "SFMono-Regular", Consolas, monospace; letter-spacing: 0.3px; word-break: break-all; }}
    .mut {{ color: var(--mut); font-weight: 800; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-top: 1px solid var(--line); padding: 7px 6px; text-align: left; vertical-align: top; }}
    th {{ color: var(--sub); font-weight: 600; }}
    .empty {{ color: var(--sub); text-align: center; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{escape_html(title)}</h1>
    <p class="note">Generated at {escape_html(now)}. Prime Editing outcomes are separated into exact intended, intended+extra, other substitution byproduct, scaffold-derived, and indel-only.</p>
    <div class="section">
      <h2>On-target Summary</h2>
      <table>
        <thead>
          <tr><th>Sample</th><th>WT (%)</th><th>Exact intended (%)</th><th>Intended+extra (%)</th><th>Other substitution (%)</th><th>Scaffold-derived (%)</th><th>Indel only (%)</th><th>Prime edited total (%)</th><th>Edit:indel</th><th>Product purity (%)</th></tr>
        </thead>
        <tbody>
          {"".join(summary_rows)}
        </tbody>
      </table>
    </div>
    <div class="section">
      <h2>Representative Alleles</h2>
      <div class="grid">
        {cards}
      </div>
    </div>
    <div class="section">
      <h2>Scaffold-derived Byproducts</h2>
      {scaffold_note}
    </div>
  </div>
</body>
</html>
"""


def render_prime_block_report_html(
    *,
    title: str,
    block: BlockSpec,
    per_sample_rows: list[dict[str, object]],
    allele_rows: list[dict[str, object]],
    scaffold_rows: list[dict[str, object]],
    heatmap_rows: list[dict[str, object]],
    heatmap_columns: list[dict[str, object]],
    heatmap_color_max_pct: float,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scale_label = _format_heatmap_scale(heatmap_color_max_pct)
    effective_scale = heatmap_color_max_pct if heatmap_color_max_pct > 0 else 5.0
    legend_ticks = [0.0, effective_scale * 0.25, effective_scale * 0.5, effective_scale * 0.75, effective_scale]
    legend_gradient = ", ".join(
        [
            f"{heatmap_color(effective_scale, effective_scale)} 0%",
            f"{heatmap_color(effective_scale * 0.75, effective_scale)} 25%",
            f"{heatmap_color(effective_scale * 0.5, effective_scale)} 50%",
            f"{heatmap_color(effective_scale * 0.25, effective_scale)} 75%",
            f"{heatmap_color(0.0, effective_scale)} 100%",
        ]
    )

    summary_rows: list[str] = []
    per_sample_by_id = {int(row["sample_id"]): row for row in per_sample_rows}
    row_lookup = {sample_id: label for label, sample_id in block.row_items}
    for label, sample_id in block.row_items:
        sample = per_sample_by_id.get(sample_id)
        if sample is None:
            continue
        summary_rows.append(
            "<tr>"
            f"<td>{escape_html(label)}</td><td>{sample_id}</td>"
            f"<td>{float(str(sample['exact_intended_pct'])):.4f}</td>"
            f"<td>{float(str(sample['intended_plus_extra_pct'])):.4f}</td>"
            f"<td>{float(str(sample['other_substitution_byproduct_pct'])):.4f}</td>"
            f"<td>{float(str(sample['scaffold_derived_pct'])):.4f}</td>"
            f"<td>{float(str(sample['indel_only_pct'])):.4f}</td>"
            f"<td>{float(str(sample['product_purity_pct'])):.4f}</td>"
            "</tr>"
        )

    cards = _render_prime_allele_tables(per_sample_rows=per_sample_rows, allele_rows=allele_rows)
    heatmap_header = ["<tr><th class='sticky'>Row</th><th class='sticky2'>Sample</th>"]
    for column in heatmap_columns:
        focus = " focus-head" if bool(column["is_highlighted"]) else ""
        intended_text = f"&rarr;{escape_html(str(column['intended_base']))}" if column["intended_base"] else ""
        heatmap_header.append(
            f"<th class='heat-head{focus}'><div>{escape_html(str(column['ref_base']))}</div><div class='sub'>{int(column['position'])}{intended_text}</div></th>"
        )
    heatmap_header.append("</tr>")

    heatmap_rows_html: list[str] = []
    for row in heatmap_rows:
        wt_class = " wt-row" if bool(row["is_wt"]) else ""
        cells = [
            f"<td class='sticky{wt_class}'>{escape_html(str(row['row_key']))}</td>",
            f"<td class='sticky2{wt_class}'>{int(row['sample_id'])}</td>",
        ]
        for column in heatmap_columns:
            value = float(str(row[str(column["field"])]))
            classes = ["heat"]
            if bool(column["is_highlighted"]):
                classes.append("focus")
            cells.append(f"<td class='{' '.join(classes)}' style='background:{heatmap_color(value, heatmap_color_max_pct)}'>{value:.2f}</td>")
        heatmap_rows_html.append(f"<tr class='heat-row{wt_class}'>" + "".join(cells) + "</tr>")

    scaffold_note = "provided" if block.scaffold_sequence else "not provided"
    scaffold_section = (
        "<p class='note'>Scaffold-derived classification used the provided scaffold motif.</p>"
        if block.scaffold_sequence
        else "<p class='note'>Scaffold-derived classification was not used because no scaffold sequence was provided.</p>"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape_html(title)}</title>
  <style>
    :root {{
      --bg: #f4f1ea;
      --ink: #1d2628;
      --mut: #c33f2c;
      --card: #fffdf9;
      --line: #d6c9b8;
      --sub: #5f655f;
      --focus: #c7512f;
      --wt: #f5f0e7;
    }}
    body {{ margin: 0; font-family: "Avenir Next", "Segoe UI", sans-serif; background: radial-gradient(circle at top right, rgba(211, 179, 117, 0.18), transparent 32%), linear-gradient(180deg, #f7f2ea 0%, #f2ede4 100%); color: var(--ink); }}
    .wrap {{ max-width: 1600px; margin: 0 auto; padding: 24px 18px 36px; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; }}
    h2 {{ margin: 0 0 12px; font-size: 20px; }}
    .note {{ color: var(--sub); margin: 0 0 8px; font-size: 14px; line-height: 1.55; }}
    .section {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 16px; margin-bottom: 16px; box-shadow: 0 8px 22px rgba(31, 28, 20, 0.06); }}
    .hero-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin-top: 12px; }}
    .hero-box {{ background: #f1eadc; border-radius: 12px; padding: 10px 12px; }}
    .hero-box .k {{ color: var(--sub); font-size: 12px; margin-bottom: 4px; }}
    .hero-box .v {{ font-size: 14px; font-weight: 700; word-break: break-all; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-top: 1px solid var(--line); padding: 8px 7px; text-align: left; vertical-align: top; }}
    th {{ color: var(--sub); font-weight: 700; background: #fbf7f0; }}
    .wt-row td {{ background: var(--wt); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 14px; }}
    .card {{ background: #fffdfa; border: 1px solid var(--line); border-radius: 14px; padding: 14px; }}
    .card-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: baseline; margin-bottom: 10px; }}
    .sid {{ font-size: 18px; font-weight: 700; }}
    .combo {{ color: var(--sub); font-size: 13px; text-align: right; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; font-size: 13px; color: var(--sub); }}
    .meta span {{ background: #f1eadc; border-radius: 999px; padding: 5px 9px; }}
    .ref {{ margin-bottom: 10px; font-size: 13px; color: var(--sub); }}
    .seq {{ font-family: "SFMono-Regular", Consolas, monospace; letter-spacing: 0.3px; word-break: break-all; }}
    .mut {{ color: var(--mut); font-weight: 800; }}
    .empty {{ color: var(--sub); text-align: center; }}
    .heat-wrap {{ overflow: auto; border: 1px solid var(--line); border-radius: 12px; }}
    .heatmap-layout {{ display: grid; grid-template-columns: minmax(0, 1fr) 120px; gap: 16px; align-items: start; }}
    .heatmap {{ min-width: 960px; }}
    .legend-box {{ border: 1px solid var(--line); border-radius: 12px; background: #fbf7f0; padding: 12px; position: sticky; top: 12px; }}
    .legend-title {{ font-size: 12px; font-weight: 700; color: var(--sub); margin-bottom: 8px; }}
    .legend-sub {{ font-size: 11px; color: var(--sub); margin-bottom: 10px; line-height: 1.45; }}
    .legend-scale {{ display: flex; align-items: stretch; gap: 10px; }}
    .legend-bar {{ width: 24px; min-width: 24px; height: 240px; border-radius: 999px; border: 1px solid rgba(0, 0, 0, 0.08); background: linear-gradient(to top, {legend_gradient}); box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.45); }}
    .legend-labels {{ height: 240px; display: flex; flex-direction: column; justify-content: space-between; font-size: 12px; color: var(--sub); font-variant-numeric: tabular-nums; }}
    .heat-head {{ text-align: center; min-width: 54px; }}
    .focus-head {{ box-shadow: inset 0 -2px 0 var(--focus); }}
    .heat {{ text-align: center; font-variant-numeric: tabular-nums; }}
    .focus {{ box-shadow: inset 0 0 0 2px rgba(199, 81, 47, 0.30); font-weight: 700; }}
    .sticky, .sticky2 {{ position: sticky; left: 0; z-index: 2; background: #fffdfa; min-width: 110px; }}
    .sticky2 {{ left: 140px; z-index: 2; }}
    .sub {{ color: var(--sub); font-size: 11px; font-weight: 400; }}
    @media (max-width: 1100px) {{
      .heatmap-layout {{ grid-template-columns: 1fr; }}
      .legend-box {{ position: static; }}
      .legend-scale {{ align-items: center; }}
      .legend-bar {{ width: 100%; height: 24px; min-width: 0; background: linear-gradient(to right, {heatmap_color(0.0, effective_scale)} 0%, {heatmap_color(effective_scale * 0.25, effective_scale)} 25%, {heatmap_color(effective_scale * 0.5, effective_scale)} 50%, {heatmap_color(effective_scale * 0.75, effective_scale)} 75%, {heatmap_color(effective_scale, effective_scale)} 100%); }}
      .legend-labels {{ height: auto; width: 100%; flex-direction: row; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{escape_html(title)}</h1>
    <p class="note">Generated at {escape_html(now)}. Prime Editing outcomes and the position heatmap are shown together in this file.</p>
    <div class="section">
      <h2>Block Summary</h2>
      <p class="note">Scaffold sequence: {escape_html(scaffold_note)}. Heatmap colors are clipped to {escape_html(scale_label)}.</p>
      <div class="hero-grid">
        <div class="hero-box"><div class="k">Block</div><div class="v">{escape_html(block.display_name)}</div></div>
        <div class="hero-box"><div class="k">Sample Scope</div><div class="v">{escape_html(block.sample_spec)}</div></div>
        <div class="hero-box"><div class="k">Target Window</div><div class="v">{escape_html(block.target_window)}</div></div>
        <div class="hero-box"><div class="k">Desired Product</div><div class="v">{escape_html(' or '.join(block.desired_products))}</div></div>
      </div>
    </div>
    <div class="section">
      <h2>On-target Summary</h2>
      <table>
        <thead>
          <tr><th>Row</th><th>Sample</th><th>Exact intended (%)</th><th>Intended+extra (%)</th><th>Other substitution (%)</th><th>Scaffold-derived (%)</th><th>Indel only (%)</th><th>Product purity (%)</th></tr>
        </thead>
        <tbody>
          {"".join(summary_rows)}
        </tbody>
      </table>
    </div>
    <div class="section">
      <h2>Representative Alleles</h2>
      <div class="grid">
        {cards}
      </div>
    </div>
    <div class="section">
      <h2>Scaffold-derived Byproducts</h2>
      {scaffold_section}
    </div>
    <div class="section">
      <h2>Position Heatmap</h2>
      <p class="note">Each cell is the intended substitution incorporation frequency at that target-window position.</p>
      <div class="heatmap-layout">
        <div class="heat-wrap">
          <table class="heatmap">
            <thead>
              {"".join(heatmap_header)}
            </thead>
            <tbody>
              {"".join(heatmap_rows_html)}
            </tbody>
          </table>
        </div>
        <div class="legend-box">
          <div class="legend-title">Color Range</div>
          <div class="legend-sub">Selected scale {escape_html(scale_label)}. Darker color means higher intended incorporation.</div>
          <div class="legend-scale">
            <div class="legend-bar" aria-hidden="true"></div>
            <div class="legend-labels">
              {"".join(f"<div>{escape_html(_format_heatmap_tick(value))}%</div>" for value in legend_ticks)}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>
"""
