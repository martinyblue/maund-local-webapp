from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from maund_workflow.run_pipeline import target_index_in_fragment

from .models import AnalysisConfig, BlockSpec, EditorPreset


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def colorize_haplotype(ref: str, hap: str) -> str:
    out: list[str] = []
    for ref_base, hap_base in zip(ref, hap):
        if ref_base == hap_base:
            out.append(hap_base)
        else:
            out.append(f'<span class="mut">{hap_base}</span>')
    return "".join(out)


def parse_same_length_haplotypes(same_length_file: Path, aseq: str, target: str) -> tuple[int, Counter[str]]:
    idx = target_index_in_fragment(aseq.upper(), target.upper())
    target_len = len(target)
    counter: Counter[str] = Counter()
    total = 0
    with same_length_file.open() as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            parts = text.split("\t")
            if len(parts) < 2:
                continue
            seq = parts[0].strip().upper()
            count = int(parts[1])
            if len(seq) < idx + target_len:
                continue
            haplotype = seq[idx : idx + target_len]
            total += count
            counter[haplotype] += count
    return total, counter


def classify_haplotype(target: str, haplotype: str, allowed: frozenset[tuple[str, str]]) -> tuple[bool, bool]:
    if haplotype == target:
        return False, False
    has_allowed = False
    for ref_base, hap_base in zip(target, haplotype):
        if ref_base == hap_base:
            continue
        if (ref_base, hap_base) in allowed:
            has_allowed = True
            continue
        return False, True
    return has_allowed, False


def build_sample_reports(
    *,
    run_rows: list[dict[str, object]],
    preset: EditorPreset,
    tail_by_sample: dict[int, dict[str, object]],
    max_haplotypes_per_sample: int = 10,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    per_sample_rows: list[dict[str, object]] = []
    ranked_rows: list[dict[str, object]] = []
    render_rows: list[dict[str, object]] = []

    for row in sorted(run_rows, key=lambda item: int(item["sample_id"])):
        if int(row["return_code"]) != 0 or not bool(row["same_length_exists"]):
            continue

        sample_id = int(row["sample_id"])
        target = str(row["rgen"]).upper()
        aseq = str(row["aseq"]).upper()
        same_length_file = Path(str(row["same_length_file"]))
        mapping = tail_by_sample.get(sample_id, {})

        total, hap_counter = parse_same_length_haplotypes(same_length_file, aseq, target)
        wt_reads = 0
        edited_reads = 0
        disallowed_reads = 0
        allowed_counter: Counter[str] = Counter()

        for haplotype, count in hap_counter.items():
            if haplotype == target:
                wt_reads += count
                continue
            is_allowed, is_disallowed = classify_haplotype(target, haplotype, preset.allowed_substitutions)
            if is_disallowed:
                disallowed_reads += count
                continue
            if is_allowed:
                edited_reads += count
                allowed_counter[haplotype] += count

        wt_pct = (wt_reads / total * 100.0) if total else 0.0
        edited_pct = (edited_reads / total * 100.0) if total else 0.0
        disallowed_pct = (disallowed_reads / total * 100.0) if total else 0.0

        sample_row = {
            "sample_id": sample_id,
            "replicate": int(row["replicate"]),
            "condition": str(row["condition"]),
            "s_index": int(row["s_index"]),
            "tail_combo": mapping.get("tail_combo", ""),
            "left_tail_module": mapping.get("left_tail_module", ""),
            "right_tail_module": mapping.get("right_tail_module", ""),
            "left_tail_sequence": mapping.get("left_tail_sequence", ""),
            "right_tail_sequence": mapping.get("right_tail_sequence", ""),
            "target_seq": target,
            "allowed_rule": preset.allowed_rule_text,
            "total_same_length_reads": total,
            "wt_reads": wt_reads,
            "wt_pct": f"{wt_pct:.6f}",
            "edited_reads_allowed_only": edited_reads,
            "edited_pct_allowed_only": f"{edited_pct:.6f}",
            "disallowed_mut_reads": disallowed_reads,
            "disallowed_mut_pct": f"{disallowed_pct:.6f}",
            "same_length_file": str(same_length_file),
        }
        per_sample_rows.append(sample_row)
        ranked_rows.append(
            {
                "sample_id": sample_id,
                "tail_combo": mapping.get("tail_combo", ""),
                "left_tail_module": mapping.get("left_tail_module", ""),
                "right_tail_module": mapping.get("right_tail_module", ""),
                "target_seq": target,
                "edited_reads_allowed_only": edited_reads,
                "total_same_length_reads": total,
                "edited_pct_allowed_only": f"{edited_pct:.6f}",
                "disallowed_mut_pct": f"{disallowed_pct:.6f}",
            }
        )

        for rank, (haplotype, count) in enumerate(allowed_counter.most_common(max_haplotypes_per_sample), start=1):
            pct = (count / total * 100.0) if total else 0.0
            render_rows.append(
                {
                    "sample_id": sample_id,
                    "tail_combo": mapping.get("tail_combo", ""),
                    "left_tail_module": mapping.get("left_tail_module", ""),
                    "right_tail_module": mapping.get("right_tail_module", ""),
                    "target_seq": target,
                    "rank": rank,
                    "haplotype": haplotype,
                    "reads": count,
                    "edited_reads_percent": f"{pct:.6f}",
                    "primary_label": preset.primary_metric_label,
                    "primary_pct": f"{edited_pct:.6f}",
                    "secondary_label": "Disallowed (%)",
                    "secondary_pct": f"{disallowed_pct:.6f}",
                    "same_length_total": total,
                }
            )

    ranked_rows.sort(
        key=lambda item: (
            -float(str(item["edited_pct_allowed_only"])),
            int(item["sample_id"]),
        )
    )
    render_rows.sort(key=lambda item: (int(item["sample_id"]), int(item["rank"])))
    return per_sample_rows, ranked_rows, render_rows


def intended_base_for_position(ref_base: str, preset: EditorPreset) -> str:
    for source, target in sorted(preset.allowed_substitutions):
        if source == ref_base:
            return target
    return ""


def desired_positions(block: BlockSpec) -> set[int]:
    positions: set[int] = set()
    for product in block.desired_products:
        for idx, (ref_base, desired_base) in enumerate(zip(block.target_window, product), start=1):
            if ref_base != desired_base:
                positions.add(idx)
    return positions


def build_heatmap_tables(
    *,
    block: BlockSpec,
    preset: EditorPreset,
    run_rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    run_rows_by_sample = {int(row["sample_id"]): row for row in run_rows}
    highlighted_positions = desired_positions(block)
    matrix_rows: list[dict[str, object]] = []
    detail_rows: list[dict[str, object]] = []
    column_specs: list[dict[str, object]] = []

    for idx, ref_base in enumerate(block.target_window, start=1):
        intended_base = intended_base_for_position(ref_base, preset)
        column_specs.append(
            {
                "position": idx,
                "ref_base": ref_base,
                "intended_base": intended_base,
                "field": f"pos_{idx:02d}_{ref_base}",
                "is_highlighted": idx in highlighted_positions,
            }
        )

    for label, sample_id in block.row_items:
        row = run_rows_by_sample.get(sample_id)
        if row is None or int(row["return_code"]) != 0 or not bool(row["same_length_exists"]):
            continue

        total, hap_counter = parse_same_length_haplotypes(
            Path(str(row["same_length_file"])),
            str(row["aseq"]),
            block.target_window,
        )
        row_label = f"{label} (sample {sample_id})"
        is_wt = "col0" in label.lower() or "wild-type" in label.lower()
        matrix_row: dict[str, object] = {
            "sample_id": sample_id,
            "row_label": row_label,
            "row_key": label,
            "is_wt": is_wt,
            "total_same_length_reads": total,
        }
        for spec in column_specs:
            intended_base = str(spec["intended_base"])
            intended_reads = 0
            if intended_base:
                intended_reads = sum(
                    count
                    for haplotype, count in hap_counter.items()
                    if len(haplotype) >= int(spec["position"]) and haplotype[int(spec["position"]) - 1] == intended_base
                )
            pct = (intended_reads / total * 100.0) if total else 0.0
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
                    "total_same_length_reads": total,
                    "intended_pct": f"{pct:.6f}",
                    "is_highlighted": bool(spec["is_highlighted"]),
                }
            )
        matrix_rows.append(matrix_row)

    return matrix_rows, detail_rows, column_specs


def _format_heatmap_scale(scale_max_pct: float) -> str:
    return f"0-{scale_max_pct:g}%"


def _format_heatmap_tick(value: float) -> str:
    rounded = round(value)
    if abs(value - rounded) < 1e-9:
        return str(int(rounded))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def heatmap_color(pct: float, scale_max_pct: float) -> str:
    effective_max = scale_max_pct if scale_max_pct > 0 else 5.0
    clipped = max(0.0, min(effective_max, pct)) / effective_max
    red = int(247 - 44 * clipped)
    green = int(247 - 74 * clipped)
    blue = int(247 - 161 * clipped)
    return f"rgb({red}, {green}, {blue})"


def _render_sample_cards(
    *,
    per_sample_rows: list[dict[str, object]],
    render_rows: list[dict[str, object]],
) -> str:
    rows_by_sample: dict[int, list[dict[str, object]]] = {}
    for row in render_rows:
        sample_id = int(row["sample_id"])
        rows_by_sample.setdefault(sample_id, []).append(row)

    cards: list[str] = []
    for sample in per_sample_rows:
        sample_id = int(sample["sample_id"])
        target = str(sample["target_seq"]).upper()
        combo = str(sample["tail_combo"]) or "Unmapped"
        rows = rows_by_sample.get(sample_id, [])
        lines = [
            '<div class="card">',
            (
                f'<div class="card-head"><div class="sid">Sample {sample_id}</div>'
                f'<div class="combo">{escape_html(combo)}</div></div>'
            ),
            (
                '<div class="meta">'
                f'<span>Edited (%): <b>{float(str(sample["edited_pct_allowed_only"])):.4f}</b></span>'
                f'<span>Disallowed (%): <b>{float(str(sample["disallowed_mut_pct"])):.4f}</b></span>'
                f'<span>Total same-length reads: <b>{int(sample["total_same_length_reads"])}</b></span>'
                "</div>"
            ),
            '<div class="ref">Ref: <span class="seq">' + target + "</span></div>",
            "<table><thead><tr><th>Rank</th><th>Haplotype</th><th>Reads</th><th>Edited reads (%)</th></tr></thead><tbody>",
        ]
        if not rows:
            lines.append('<tr><td colspan="4" class="empty">No allowed haplotype found</td></tr>')
        else:
            for row in rows:
                colored = colorize_haplotype(target, str(row["haplotype"]))
                lines.append(
                    f"<tr><td>{int(row['rank'])}</td><td><span class='seq'>{colored}</span></td>"
                    f"<td>{int(row['reads'])}</td><td>{float(str(row['edited_reads_percent'])):.4f}</td></tr>"
                )
        lines.append("</tbody></table>")
        lines.append("</div>")
        cards.append("\n".join(lines))
    return "\n".join(cards)


def render_html(
    *,
    per_sample_rows: list[dict[str, object]],
    render_rows: list[dict[str, object]],
    title: str,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cards = _render_sample_cards(per_sample_rows=per_sample_rows, render_rows=render_rows)
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
    .wrap {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 24px 18px 32px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 28px;
      letter-spacing: 0.15px;
    }}
    .note {{
      margin: 0 0 18px;
      color: var(--sub);
      font-size: 14px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
      gap: 14px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      box-shadow: 0 8px 22px rgba(31, 28, 20, 0.06);
    }}
    .card-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 10px;
    }}
    .sid {{
      font-size: 18px;
      font-weight: 700;
    }}
    .combo {{
      color: var(--sub);
      font-size: 13px;
      text-align: right;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 10px;
      font-size: 13px;
      color: var(--sub);
    }}
    .meta span {{
      background: #f1eadc;
      border-radius: 999px;
      padding: 5px 9px;
    }}
    .ref {{
      margin-bottom: 10px;
      font-size: 13px;
      color: var(--sub);
    }}
    .seq {{
      font-family: "SFMono-Regular", Consolas, monospace;
      letter-spacing: 0.3px;
      word-break: break-all;
    }}
    .mut {{
      color: var(--mut);
      font-weight: 800;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      border-top: 1px solid var(--line);
      padding: 7px 6px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--sub);
      font-weight: 600;
    }}
    .empty {{
      color: var(--sub);
      text-align: center;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{escape_html(title)}</h1>
    <p class="note">Generated at {escape_html(now)}. Only changed bases are colored.</p>
    <div class="grid">
      {cards}
    </div>
  </div>
</body>
</html>
"""


def render_block_report_html(
    *,
    title: str,
    block: BlockSpec,
    preset: EditorPreset,
    per_sample_rows: list[dict[str, object]],
    ranked_rows: list[dict[str, object]],
    render_rows: list[dict[str, object]],
    heatmap_rows: list[dict[str, object]],
    heatmap_columns: list[dict[str, object]],
    heatmap_color_max_pct: float,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scale_label = _format_heatmap_scale(heatmap_color_max_pct)
    effective_scale = heatmap_color_max_pct if heatmap_color_max_pct > 0 else 5.0
    legend_ticks = [
        0.0,
        effective_scale * 0.25,
        effective_scale * 0.5,
        effective_scale * 0.75,
        effective_scale,
    ]
    legend_gradient = ", ".join(
        [
            f"{heatmap_color(effective_scale, effective_scale)} 0%",
            f"{heatmap_color(effective_scale * 0.75, effective_scale)} 25%",
            f"{heatmap_color(effective_scale * 0.5, effective_scale)} 50%",
            f"{heatmap_color(effective_scale * 0.25, effective_scale)} 75%",
            f"{heatmap_color(0.0, effective_scale)} 100%",
        ]
    )
    per_sample_by_id = {int(row["sample_id"]): row for row in per_sample_rows}
    ranked_by_id = {int(row["sample_id"]): row for row in ranked_rows}
    desired_text = " or ".join(block.desired_products)
    summary_rows: list[str] = []
    ranked_table_rows: list[str] = []
    row_lookup = {sample_id: label for label, sample_id in block.row_items}

    for label, sample_id in block.row_items:
        sample = per_sample_by_id.get(sample_id)
        if sample is None:
            continue
        wt_class = " class='wt-row'" if "col0" in label.lower() or "wild-type" in label.lower() else ""
        summary_rows.append(
            f"<tr{wt_class}><td>{escape_html(label)}</td><td>{sample_id}</td>"
            f"<td>{float(str(sample['edited_pct_allowed_only'])):.4f}</td>"
            f"<td>{float(str(sample['disallowed_mut_pct'])):.4f}</td>"
            f"<td>{int(sample['total_same_length_reads'])}</td></tr>"
        )

    for row in ranked_rows:
        sample_id = int(row["sample_id"])
        label = row_lookup.get(sample_id, f"sample {sample_id}")
        ranked_table_rows.append(
            "<tr>"
            f"<td>{escape_html(label)}</td><td>{sample_id}</td>"
            f"<td>{float(str(row['edited_pct_allowed_only'])):.4f}</td>"
            f"<td>{int(row['edited_reads_allowed_only'])}</td>"
            f"<td>{int(row['total_same_length_reads'])}</td>"
            "</tr>"
        )

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
            cells.append(
                f"<td class='{' '.join(classes)}' style='background:{heatmap_color(value, heatmap_color_max_pct)}'>{value:.2f}</td>"
            )
        heatmap_rows_html.append(f"<tr class='heat-row{wt_class}'>" + "".join(cells) + "</tr>")

    heatmap_header = ["<tr><th class='sticky'>Row</th><th class='sticky2'>Sample</th>"]
    for column in heatmap_columns:
        focus = " focus-head" if bool(column["is_highlighted"]) else ""
        intended_text = f"&rarr;{escape_html(str(column['intended_base']))}" if column["intended_base"] else ""
        heatmap_header.append(
            f"<th class='heat-head{focus}'><div>{escape_html(str(column['ref_base']))}</div>"
            f"<div class='sub'>{int(column['position'])}{intended_text}</div></th>"
        )
    heatmap_header.append("</tr>")

    cards = _render_sample_cards(per_sample_rows=per_sample_rows, render_rows=render_rows)
    desired_note = (
        f"<div class='product'>Desired products: {escape_html(desired_text)}</div>"
        if desired_text
        else "<div class='product'>Desired products: not provided</div>"
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
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top right, rgba(211, 179, 117, 0.18), transparent 32%),
        linear-gradient(180deg, #f7f2ea 0%, #f2ede4 100%);
      color: var(--ink);
    }}
    .wrap {{
      max-width: 1600px;
      margin: 0 auto;
      padding: 24px 18px 36px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 30px;
    }}
    h2 {{
      margin: 0 0 12px;
      font-size: 20px;
    }}
    .note, .product {{
      color: var(--sub);
      margin: 0 0 8px;
      font-size: 14px;
      line-height: 1.55;
    }}
    .section {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
      margin-bottom: 16px;
      box-shadow: 0 8px 22px rgba(31, 28, 20, 0.06);
    }}
    .hero-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
      margin-top: 12px;
    }}
    .hero-box {{
      background: #f1eadc;
      border-radius: 12px;
      padding: 10px 12px;
    }}
    .hero-box .k {{
      color: var(--sub);
      font-size: 12px;
      margin-bottom: 4px;
    }}
    .hero-box .v {{
      font-size: 14px;
      font-weight: 700;
      word-break: break-all;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      border-top: 1px solid var(--line);
      padding: 8px 7px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--sub);
      font-weight: 700;
      background: #fbf7f0;
    }}
    .wt-row td {{
      background: var(--wt);
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
      gap: 14px;
    }}
    .card {{
      background: #fffdfa;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
    }}
    .card-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 10px;
    }}
    .sid {{
      font-size: 18px;
      font-weight: 700;
    }}
    .combo {{
      color: var(--sub);
      font-size: 13px;
      text-align: right;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 10px;
      font-size: 13px;
      color: var(--sub);
    }}
    .meta span {{
      background: #f1eadc;
      border-radius: 999px;
      padding: 5px 9px;
    }}
    .ref {{
      margin-bottom: 10px;
      font-size: 13px;
      color: var(--sub);
    }}
    .seq {{
      font-family: "SFMono-Regular", Consolas, monospace;
      letter-spacing: 0.3px;
      word-break: break-all;
    }}
    .mut {{
      color: var(--mut);
      font-weight: 800;
    }}
    .empty {{
      color: var(--sub);
      text-align: center;
    }}
    .heat-wrap {{
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 12px;
    }}
    .heatmap-layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 120px;
      gap: 16px;
      align-items: start;
    }}
    .heatmap {{
      min-width: 960px;
    }}
    .legend-box {{
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fbf7f0;
      padding: 12px;
      position: sticky;
      top: 12px;
    }}
    .legend-title {{
      font-size: 12px;
      font-weight: 700;
      color: var(--sub);
      margin-bottom: 8px;
    }}
    .legend-sub {{
      font-size: 11px;
      color: var(--sub);
      margin-bottom: 10px;
      line-height: 1.45;
    }}
    .legend-scale {{
      display: flex;
      align-items: stretch;
      gap: 10px;
    }}
    .legend-bar {{
      width: 24px;
      min-width: 24px;
      height: 240px;
      border-radius: 999px;
      border: 1px solid rgba(0, 0, 0, 0.08);
      background: linear-gradient(to top, {legend_gradient});
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.45);
    }}
    .legend-labels {{
      height: 240px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      font-size: 12px;
      color: var(--sub);
      font-variant-numeric: tabular-nums;
    }}
    .legend-labels div {{
      line-height: 1;
    }}
    .heat-head {{
      text-align: center;
      min-width: 54px;
    }}
    .focus-head {{
      box-shadow: inset 0 -2px 0 var(--focus);
    }}
    .heat {{
      text-align: center;
      font-variant-numeric: tabular-nums;
    }}
    .focus {{
      box-shadow: inset 0 0 0 2px rgba(199, 81, 47, 0.30);
      font-weight: 700;
    }}
    .sticky, .sticky2 {{
      position: sticky;
      left: 0;
      z-index: 2;
      background: #fffdfa;
    }}
    .sticky2 {{
      left: 140px;
      z-index: 2;
    }}
    .sticky, .sticky2 {{
      min-width: 110px;
    }}
    .sub {{
      color: var(--sub);
      font-size: 11px;
      font-weight: 400;
    }}
    @media (max-width: 1100px) {{
      .heatmap-layout {{
        grid-template-columns: 1fr;
      }}
      .legend-box {{
        position: static;
      }}
      .legend-scale {{
        align-items: center;
      }}
      .legend-bar {{
        width: 100%;
        height: 24px;
        min-width: 0;
        background: linear-gradient(to right, {heatmap_color(0.0, effective_scale)} 0%, {heatmap_color(effective_scale * 0.25, effective_scale)} 25%, {heatmap_color(effective_scale * 0.5, effective_scale)} 50%, {heatmap_color(effective_scale * 0.75, effective_scale)} 75%, {heatmap_color(effective_scale, effective_scale)} 100%);
      }}
      .legend-labels {{
        height: auto;
        width: 100%;
        flex-direction: row;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{escape_html(title)}</h1>
    <p class="note">Generated at {escape_html(now)}. Existing MAUND outputs and the new heatmap are shown together in this file.</p>
    <div class="section">
      <h2>Block Summary</h2>
      <p class="note">Rule: {escape_html(preset.allowed_rule_text)}. Heatmap colors are clipped to {escape_html(scale_label)}, while cell numbers show the real percentage.</p>
      {desired_note}
      <div class="hero-grid">
        <div class="hero-box"><div class="k">Block</div><div class="v">{escape_html(block.display_name)}</div></div>
        <div class="hero-box"><div class="k">Sample Scope</div><div class="v">{escape_html(block.sample_spec)}</div></div>
        <div class="hero-box"><div class="k">Target Window</div><div class="v">{escape_html(block.target_window)}</div></div>
        <div class="hero-box"><div class="k">Rows</div><div class="v">{len(heatmap_rows)}</div></div>
        <div class="hero-box"><div class="k">Color Scale</div><div class="v">{escape_html(scale_label)}</div></div>
      </div>
    </div>

    <div class="section">
      <h2>Per-sample Editing Summary</h2>
      <table>
        <thead>
          <tr><th>Row</th><th>Sample</th><th>Edited (%)</th><th>Disallowed (%)</th><th>Total same-length reads</th></tr>
        </thead>
        <tbody>
          {"".join(summary_rows)}
        </tbody>
      </table>
    </div>

    <div class="section">
      <h2>Ranked Editing</h2>
      <table>
        <thead>
          <tr><th>Row</th><th>Sample</th><th>Edited (%)</th><th>Edited reads</th><th>Total same-length reads</th></tr>
        </thead>
        <tbody>
          {"".join(ranked_table_rows)}
        </tbody>
      </table>
    </div>

    <div class="section">
      <h2>Haplotype Cards</h2>
      <div class="grid">
        {cards}
      </div>
    </div>

    <div class="section">
      <h2>Position Heatmap</h2>
      <p class="note">Each cell is the intended conversion frequency at that target-window position. Colors use the selected {escape_html(scale_label)} scale.</p>
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
          <div class="legend-sub">Selected scale {escape_html(scale_label)}. Darker color means higher intended editing frequency.</div>
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


def build_analysis_flow_markdown(
    *,
    config: AnalysisConfig,
    preset: EditorPreset,
    selected_sample_ids: list[int],
    outputs: list[Path],
    warnings: list[str],
    block_summaries: list[str] | None = None,
) -> str:
    is_prime = preset.analysis_family == "prime_editing"
    lines = [
        f"# Analysis Flow ({config.date_tag})",
        "",
        "## Scope",
        "- Mode: " + config.analysis_mode,
        "- Samples: " + ",".join(str(sample_id) for sample_id in selected_sample_ids),
    ]
    if config.analysis_mode == "single_target":
        lines.extend([f"- Target: {config.target_seq.upper()}", f"- Editor: {preset.label}"])
        if is_prime:
            lines.extend(
                [
                    f"- Desired product(s): {', '.join(config.desired_products) or 'not provided'}",
                    f"- Scaffold sequence: {config.scaffold_sequence or 'not provided'}",
                    "",
                    "## Steps",
                    "1. Discover FASTQ pairs and merge with fixed offset (29)",
                    "2. Run MAUND-compatible lite extraction per sample and keep both same-length and all-read outputs",
                    "3. Classify each read into WT, exact intended, intended+extra, other substitution, optional scaffold-derived, or indel-only",
                    "4. Build prime-editing summary tables, representative allele tables, and position heatmap",
                    "5. Write prime HTML report and reusable table outputs",
                ]
            )
        else:
            lines.extend(
                [
                    f"- Rule: {preset.allowed_rule_text}",
                    "",
                    "## Steps",
                    "1. Discover FASTQ pairs and merge with fixed offset (29)",
                    "2. Run MAUND-compatible lite extraction per sample and keep same-length outputs",
                    "3. Count allowed-only OR-edited haplotypes per sample",
                    "4. Build ranked per-sample haplotype tables and HTML cards",
                    "5. Write run notes and reusable table outputs",
                ]
            )
    else:
        lines.extend([f"- Editor: {preset.label}", f"- Heatmap color scale: {_format_heatmap_scale(config.heatmap_color_max_pct)}"])
        if is_prime:
            lines.extend(
                [
                    f"- Global desired product default(s): {', '.join(config.desired_products) or 'not provided'}",
                    f"- Global scaffold default: {config.scaffold_sequence or 'not provided'}",
                    "",
                    "## Steps",
                    "1. Parse block definitions from seq xlsx, or infer a single block from flat prime-editing xlsx",
                    "2. Merge all needed FASTQ pairs and run MAUND-compatible lite extraction for each block",
                    "3. Classify reads into prime-editing outcome classes for each block target",
                    "4. Compute position-wise intended incorporation heatmaps for each block",
                    "5. Save per-block prime HTML, TSV outputs, and run notes",
                ]
            )
        else:
            lines.extend(
                [
                    f"- Rule: {preset.allowed_rule_text}",
                    "",
                    "## Steps",
                    "1. Parse block definitions from seq xlsx and merge all needed FASTQ pairs",
                    "2. Run MAUND-compatible lite extraction separately for each block target",
                    "3. Write block-specific MAUND tables and combined HTML reports",
                    "4. Compute position-wise intended conversion heatmaps for each block",
                    "5. Save per-block HTML, TSV outputs, and run notes",
                ]
            )
        if block_summaries:
            lines.extend(["", "## Blocks"])
            for summary in block_summaries:
                lines.append(f"- {summary}")
    lines.extend(["", "## Outputs"])
    for output in outputs:
        lines.append(f"- {output.name}")
    if warnings:
        lines.extend(["", "## Warnings"])
        for warning in warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines) + "\n"
