from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from maund_workflow.run_pipeline import target_index_in_fragment

from .models import AnalysisConfig, EditorPreset


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


def render_html(
    *,
    per_sample_rows: list[dict[str, object]],
    render_rows: list[dict[str, object]],
    title: str,
) -> str:
    rows_by_sample: dict[int, list[dict[str, object]]] = {}
    for row in render_rows:
        sample_id = int(row["sample_id"])
        rows_by_sample.setdefault(sample_id, []).append(row)

    cards: list[str] = []
    for sample in sorted(per_sample_rows, key=lambda item: int(item["sample_id"])):
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
                f'<span>{escape_html(str(render_rows[0]["primary_label"]) if render_rows else "Edited (%)")}: '
                f'<b>{float(str(sample["edited_pct_allowed_only"])):.4f}</b></span>'
                f'<span>Disallowed (%): <b>{float(str(sample["disallowed_mut_pct"])):.4f}</b></span>'
                f'<span>Total same-length reads: <b>{int(sample["total_same_length_reads"])}</b></span>'
                "</div>"
            ),
            '<div class="ref">Ref: <span class="seq">' + target + "</span></div>",
            "<table><thead><tr><th>Rank</th><th>Haplotype (changed bases only)</th><th>Reads</th><th>Edited reads (%)</th></tr></thead><tbody>",
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

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
      {"".join(cards)}
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
) -> str:
    lines = [
        f"# Analysis Flow ({config.date_tag})",
        "",
        "## Scope",
        "- Samples: " + ",".join(str(sample_id) for sample_id in selected_sample_ids),
        f"- Target: {config.target_seq.upper()}",
        f"- Editor: {preset.label}",
        f"- Rule: {preset.allowed_rule_text}",
        "",
        "## Steps",
        "1. Discover FASTQ pairs and merge with fixed offset (29)",
        "2. Run MAUND-compatible lite extraction per sample and keep same-length outputs",
        "3. Count allowed-only OR-edited haplotypes per sample",
        "4. Build ranked per-sample haplotype tables and HTML cards",
        "5. Write run notes and reusable table outputs",
        "",
        "## Outputs",
    ]
    for output in outputs:
        lines.append(f"- {output.name}")
    if warnings:
        lines.extend(["", "## Warnings"])
        for warning in warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines) + "\n"
