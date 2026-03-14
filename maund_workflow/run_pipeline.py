#!/usr/bin/env python3
"""
MAUND automation pipeline.

Creates two folders:
1) maund_<date_tag>      : full MAUND run outputs and summary tables
2) maund_<date_tag>_2    : panel-like top edited haplotype tables

Default date_tag format: yymmdd
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import re
import shutil
import statistics
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
DEFAULT_CONVERSION_RULES = (
    "GCTCACGGTTATTTTGGCCGAT:A>G,T>C;"
    "GGGCATTACTTGAATGCTACTGCGGGT:C>T,G>A"
)
DEFAULT_KEY_MOTIF_RULES = (
    "GCTCACGGTTATTTTGGCCGAT:TAT>TGT;"
    "GGGCATTACTTGAATGCTACTGCGGGT:GCT>GTT"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MAUND workflow for new FASTQ datasets.")
    parser.add_argument("--fastq-dir", required=True, help="Directory containing paired FASTQ files.")
    parser.add_argument("--seq-xlsx", required=True, help="Path to sequence mapping xlsx file.")
    parser.add_argument(
        "--base-dir",
        default=str(Path.cwd()),
        help="Base directory where maund_<date> folders will be created.",
    )
    parser.add_argument(
        "--maund-home",
        default=str((Path(__file__).resolve().parent.parent / "maund_practice").resolve()),
        help="Directory containing libmaund and .venv2 python.",
    )
    parser.add_argument(
        "--date-tag",
        default=datetime.now().strftime("%y%m%d"),
        help="Date tag used in output folder names. Example: 260226",
    )
    parser.add_argument(
        "--condition",
        default="one_condition",
        help="Condition label used in summary tables.",
    )
    parser.add_argument(
        "--exclude-samples",
        default="",
        help="Comma-separated sample IDs to exclude. Example: 93,101",
    )
    parser.add_argument(
        "--sample-ids",
        default="",
        help="Optional comma-separated sample IDs to run only subset.",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=29,
        help="Fixed merge offset for R1 and reverse-complement R2.",
    )
    parser.add_argument(
        "--otag",
        default="auto",
        help="MAUND output tag used in filenames.",
    )
    parser.add_argument(
        "--conversion-rules",
        default=DEFAULT_CONVERSION_RULES,
        help=(
            "Full-target conversion rules for step2 panel analysis. "
            "Format: target:A>G,T>C;target2:C>T,G>A"
        ),
    )
    parser.add_argument(
        "--key-motif-rules",
        default=DEFAULT_KEY_MOTIF_RULES,
        help=(
            "Key motif conversion rules for step2 motif summary. "
            "Format: target:TAT>TGT;target2:GCT>GTT"
        ),
    )
    return parser.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def setup_work_dirs(root: Path) -> Dict[str, Path]:
    dirs = {
        "root": root,
        "merged": root / "merged_fastq",
        "maund_out": root / "maund_out",
        "logs": root / "logs",
        "tables": root / "tables",
    }
    for d in dirs.values():
        ensure_dir(d)
    return dirs


def parse_id_spec(spec: str) -> List[int]:
    out: List[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "~" in part:
            a, b = part.split("~", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def parse_xlsx_mapping(xlsx_path: Path) -> Dict[int, Dict[str, str]]:
    """Returns sample_id -> {aseq, rgen}."""
    with zipfile.ZipFile(xlsx_path) as zf:
        shared_strings: List[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("a:si", NS):
                txt = "".join((t.text or "") for t in si.findall(".//a:t", NS))
                shared_strings.append(txt)

        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        sheet = wb.find("a:sheets/a:sheet", NS)
        if sheet is None:
            raise RuntimeError("No sheet found in xlsx workbook.")

        rid = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        if not rid:
            raise RuntimeError("Sheet relationship id not found.")

        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_map = {
            r.attrib["Id"]: r.attrib["Target"]
            for r in rels.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
        }
        ws_target = rel_map.get(rid)
        if not ws_target:
            raise RuntimeError("Worksheet target not found in workbook rels.")

        ws = ET.fromstring(zf.read("xl/" + ws_target))

    rows: List[List[str]] = []
    for row in ws.findall("a:sheetData/a:row", NS):
        vals: List[str] = []
        for cell in row.findall("a:c", NS):
            ctype = cell.attrib.get("t")
            v = cell.find("a:v", NS)
            if v is None:
                vals.append("")
                continue
            raw = v.text or ""
            if ctype == "s" and raw.isdigit():
                idx = int(raw)
                vals.append(shared_strings[idx] if idx < len(shared_strings) else "")
            else:
                vals.append(raw)
        rows.append(vals)

    # Expected layout from today's file:
    # row1: headers, row2 blank, row3+ data
    mapping: Dict[int, Dict[str, str]] = {}
    for row in rows[2:]:
        if len(row) < 3:
            continue
        id_spec = (row[0] or "").strip()
        aseq = (row[1] or "").strip().upper()
        rgen = (row[2] or "").strip().upper()
        if not id_spec or not aseq or not rgen:
            continue
        for sid in parse_id_spec(id_spec):
            mapping[sid] = {"aseq": aseq, "rgen": rgen}
    return mapping


def discover_fastq_pairs(fastq_dir: Path) -> Dict[int, Dict[str, object]]:
    """Returns sample_id -> {r1, r2, s_index}."""
    pairs: Dict[int, Dict[str, object]] = {}
    regex = re.compile(r"^(\d+)_S(\d+)_L\d+_R1_001\.fastq\.gz$")
    for r1 in sorted(fastq_dir.glob("*_R1_001.fastq.gz")):
        m = regex.match(r1.name)
        if not m:
            continue
        sid = int(m.group(1))
        s_index = int(m.group(2))
        r2 = fastq_dir / r1.name.replace("_R1_001.fastq.gz", "_R2_001.fastq.gz")
        if r2.exists():
            pairs[sid] = {"r1": r1, "r2": r2, "s_index": s_index}
    return pairs


TRANS = str.maketrans("ACGTN", "TGCAN")


def revcomp(seq: str) -> str:
    return seq.translate(TRANS)[::-1]


def merge_fixed_offset(r1: str, r2_rc: str, offset: int) -> Tuple[str, int, int]:
    start = min(0, offset)
    end = max(len(r1), offset + len(r2_rc))
    out: List[str] = []
    ov = 0
    match = 0
    for pos in range(start, end):
        c1 = r1[pos] if 0 <= pos < len(r1) else None
        c2 = r2_rc[pos - offset] if 0 <= pos - offset < len(r2_rc) else None
        if c1 is not None and c2 is not None:
            ov += 1
            if c1 == c2:
                match += 1
        if c1 is None:
            out.append(c2)  # type: ignore[arg-type]
        elif c2 is None:
            out.append(c1)
        elif c1 == c2:
            out.append(c1)
        else:
            out.append(c1)
    return "".join(out), match, ov


def merge_samples(
    sample_ids: Iterable[int],
    pairs: Dict[int, Dict[str, object]],
    merged_dir: Path,
    offset: int,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for sid in sorted(sample_ids):
        pair = pairs[sid]
        r1 = pair["r1"]  # type: ignore[assignment]
        r2 = pair["r2"]  # type: ignore[assignment]
        merged_path = merged_dir / f"{sid}.merged.fastq"

        n_reads = 0
        total_match = 0
        total_ov = 0
        with gzip.open(r1, "rt") as f1, gzip.open(r2, "rt") as f2, merged_path.open("w") as fout:
            while True:
                h1 = f1.readline()
                if not h1:
                    break
                seq1 = f1.readline().strip()
                f1.readline()
                f1.readline()
                f2.readline()
                seq2 = f2.readline().strip()
                f2.readline()
                f2.readline()

                merged_seq, m, ov = merge_fixed_offset(seq1, revcomp(seq2), offset)
                n_reads += 1
                total_match += m
                total_ov += ov
                fout.write(f"@{sid}_{n_reads}\n{merged_seq}\n+\n" + ("I" * len(merged_seq)) + "\n")

        ratio = (total_match / total_ov) if total_ov else 0.0
        rows.append(
            {
                "sample_id": sid,
                "s_index": pair["s_index"],
                "read_count": n_reads,
                "offset": offset,
                "overlap_match_ratio": f"{ratio:.4f}",
                "merged_fastq": str(merged_path),
            }
        )
    return rows


def run_maund(
    sample_ids: Iterable[int],
    mapping: Dict[int, Dict[str, str]],
    pairs: Dict[int, Dict[str, object]],
    merged_dir: Path,
    maund_out_dir: Path,
    logs_dir: Path,
    maund_home: Path,
    python_bin: Path,
    otag: str,
    condition: str,
) -> List[Dict[str, object]]:
    run_rows: List[Dict[str, object]] = []
    for replicate, sid in enumerate(sorted(sample_ids), start=1):
        aseq = mapping[sid]["aseq"]
        rgen = mapping[sid]["rgen"]
        s_index = pairs[sid]["s_index"]  # type: ignore[assignment]

        merged_path = merged_dir / f"{sid}.merged.fastq"
        local_link = maund_out_dir / merged_path.name
        if local_link.exists() or local_link.is_symlink():
            local_link.unlink()
        local_link.symlink_to(merged_path)

        cmd = [
            str(python_bin),
            "-m",
            "libmaund",
            aseq,
            rgen,
            "--no_reverse_complement_match",
            "-otag",
            otag,
            local_link.name,
        ]

        env = dict(os.environ)
        env["PYTHONPATH"] = str(maund_home)

        proc = subprocess.run(
            cmd,
            cwd=str(maund_out_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        log_file = logs_dir / f"{sid}.log"
        log_file.write_text(proc.stdout)

        summary_file = maund_out_dir / f"{local_link.name}.{rgen}.maund.{otag}.Miseq_summary.txt"
        window_file = maund_out_dir / f"{local_link.name}.{rgen}.maund.{otag}._window.txt"
        same_length_file = maund_out_dir / f"{local_link.name}.{rgen}.maund.{otag}._same_length.txt"

        run_rows.append(
            {
                "sample_id": sid,
                "replicate": replicate,
                "condition": condition,
                "s_index": s_index,
                "aseq": aseq,
                "rgen": rgen,
                "return_code": proc.returncode,
                "summary_file": str(summary_file),
                "summary_exists": summary_file.exists(),
                "window_file": str(window_file),
                "window_exists": window_file.exists(),
                "same_length_file": str(same_length_file),
                "same_length_exists": same_length_file.exists(),
                "log_file": str(log_file),
            }
        )
    return run_rows


def parse_summary_file(path: Path) -> Dict[str, object]:
    vals = path.read_text().strip().split("\t")
    out: Dict[str, object] = {}
    if len(vals) >= 8:
        out["input_file"] = vals[0]
        out["target_seq"] = vals[1]
        out["window_mutated"] = int(vals[2])
        out["window_total"] = int(vals[3])
        out["window_ratio"] = None if vals[4].lower() == "nan" else float(vals[4])
        out["n_indels"] = int(vals[5])
        out["n_all"] = int(vals[6])
        out["indel_ratio"] = None if vals[7].lower() == "nan" else float(vals[7])
    return out


def compute_edited_reads(run_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for r in run_rows:
        if not bool(r["window_exists"]):
            continue
        sid = int(r["sample_id"])
        rgen = str(r["rgen"])
        wt_window = rgen[3:7]
        wfile = Path(str(r["window_file"]))

        total = 0
        wt_count = 0
        with wfile.open() as f:
            next(f, None)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                w, n = line.split("\t")
                n_int = int(n)
                total += n_int
                if w == wt_window:
                    wt_count += n_int

        edited_pct = None
        if total > 0:
            edited_pct = (1.0 - wt_count / total) * 100.0

        svals: Dict[str, object] = {}
        if bool(r["summary_exists"]):
            svals = parse_summary_file(Path(str(r["summary_file"])))

        rows.append(
            {
                "sample_id": sid,
                "replicate": r["replicate"],
                "condition": r["condition"],
                "s_index": r["s_index"],
                "target_window_ref": wt_window,
                "window_total_reads": total,
                "window_wt_reads": wt_count,
                "edited_reads_percent": "" if edited_pct is None else f"{edited_pct:.6f}",
                "maund_window_mutated": svals.get("window_mutated", ""),
                "maund_window_total": svals.get("window_total", ""),
                "maund_window_ratio": ""
                if svals.get("window_ratio", None) is None
                else f"{float(svals['window_ratio']):.6f}",
                "maund_n_indels": svals.get("n_indels", ""),
                "maund_n_all": svals.get("n_all", ""),
                "maund_indel_ratio": ""
                if svals.get("indel_ratio", None) is None
                else f"{float(svals['indel_ratio']):.6f}",
            }
        )
    return rows


def condition_summary(edited_rows: List[Dict[str, object]], condition: str) -> Dict[str, object]:
    values = [float(r["edited_reads_percent"]) for r in edited_rows if str(r["edited_reads_percent"]) != ""]
    mean_v = statistics.mean(values) if values else None
    sd_v = statistics.stdev(values) if len(values) > 1 else None
    return {
        "condition": condition,
        "n_samples": len(values),
        "edited_reads_mean_percent": "" if mean_v is None else f"{mean_v:.6f}",
        "edited_reads_sd_percent": "" if sd_v is None else f"{sd_v:.6f}",
    }


def target_index_in_fragment(aseq: str, rgen: str, comparison_range: int = 60) -> int:
    """
    Infer target start index in MAUND same-length fragment.
    Mirrors MAUND range selection logic.
    """
    aseq = aseq.upper()
    rgen = rgen.upper()
    i = aseq.find(rgen)
    if i == -1:
        raise ValueError(f"rgen not found in aseq: {rgen}")
    idx_cleavage = len(rgen) - 6
    start_pos = i + idx_cleavage - comparison_range
    end_pos = i + idx_cleavage + comparison_range
    if start_pos < 0:
        start_pos = 0
    if end_pos > len(aseq):
        end_pos = len(aseq)
    seq_range = aseq[start_pos:end_pos]
    i_rgen = seq_range.find(rgen)
    if i_rgen == -1:
        i_rgen = i - start_pos
    return i_rgen


def has_motif_conversion(target: str, haplotype: str, motif_src: str, motif_dst: str) -> bool:
    target = target.upper()
    haplotype = haplotype.upper()
    motif_src = motif_src.upper()
    motif_dst = motif_dst.upper()
    mlen = len(motif_src)
    if len(motif_src) != len(motif_dst) or mlen == 0:
        return False
    for i in range(0, len(target) - mlen + 1):
        if target[i : i + mlen] == motif_src and haplotype[i : i + mlen] == motif_dst:
            return True
    return False


def is_allowed_only_haplotype(target: str, haplotype: str, allowed: set[Tuple[str, str]]) -> bool:
    has_edit = False
    for ref, alt in zip(target, haplotype):
        if ref == alt:
            continue
        has_edit = True
        if (ref, alt) not in allowed:
            return False
    return has_edit


def decorate_haplotype_for_md(target: str, haplotype: str, allowed: set[Tuple[str, str]]) -> str:
    """
    Return plain-text haplotype for markdown output.
    (No color markup; backtick-wrapped for readability.)
    """
    haplotype = haplotype.upper()
    return f"`{haplotype}`"


def decorate_haplotype_for_html(target: str, haplotype: str, allowed: set[Tuple[str, str]]) -> str:
    target = target.upper()
    haplotype = haplotype.upper()
    parts: List[str] = []
    for ref, alt in zip(target, haplotype):
        if ref != alt and (ref, alt) in allowed:
            parts.append(f'<span class="edited">{alt}</span>')
        else:
            parts.append(alt)
    return f'<span class="hap">{"".join(parts)}</span>'


def generate_panel_like_tables(
    run_rows: List[Dict[str, object]],
    out_tsv: Path,
    out_md: Path,
    conversion_rules: Dict[str, set[Tuple[str, str]]],
    out_tables_dir: Path,
) -> None:
    """
    Full-target panel analysis.

    A case is counted only when:
    - full target haplotype has >=1 substitution
    - every substitution belongs to allowed conversion rules for that target
    """
    grouped: Dict[Tuple[str, str], List[Dict[str, object]]] = defaultdict(list)
    skipped_targets: set[str] = set()
    for r in run_rows:
        if int(r["return_code"]) != 0:
            continue
        if not bool(r["same_length_exists"]):
            continue
        target = str(r["rgen"]).upper()
        if target not in conversion_rules:
            skipped_targets.add(target)
            continue
        grouped[(str(r["condition"]), target)].append(r)

    sample_rows: List[Dict[str, object]] = []
    case_pct_by_group: Dict[Tuple[str, str], Dict[str, Dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    samples_by_group: Dict[Tuple[str, str], List[int]] = defaultdict(list)

    for (condition, target), samples in sorted(grouped.items(), key=lambda x: x[0][1]):
        allowed = conversion_rules[target]
        for s in samples:
            sid = int(s["sample_id"])
            aseq = str(s["aseq"]).upper()
            same_length_file = Path(str(s["same_length_file"]))
            idx = target_index_in_fragment(aseq, target)
            tlen = len(target)

            total_reads = 0
            wt_reads = 0
            edited_reads = 0
            disallowed_reads = 0
            case_counts: Dict[str, int] = defaultdict(int)

            with same_length_file.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("\t")
                    if len(parts) < 2:
                        continue
                    seq = parts[0].strip().upper()
                    n = int(parts[1])
                    if len(seq) < idx + tlen:
                        continue

                    hap = seq[idx : idx + tlen]
                    total_reads += n

                    if hap == target:
                        wt_reads += n
                        continue

                    allowed_only = is_allowed_only_haplotype(target, hap, allowed)
                    has_allowed = hap != target and allowed_only
                    if not allowed_only and hap != target:
                        disallowed_reads += n
                        continue
                    if has_allowed:
                        edited_reads += n
                        case_counts[hap] += n

            wt_pct = (wt_reads / total_reads * 100.0) if total_reads else 0.0
            edited_pct = (edited_reads / total_reads * 100.0) if total_reads else 0.0
            disallowed_pct = (disallowed_reads / total_reads * 100.0) if total_reads else 0.0

            sample_rows.append(
                {
                    "sample_id": sid,
                    "replicate": s["replicate"],
                    "condition": condition,
                    "target_seq": target,
                    "allowed_conversions": ",".join(f"{a}>{b}" for (a, b) in sorted(allowed)),
                    "total_same_length_reads": total_reads,
                    "wt_reads": wt_reads,
                    "wt_pct": f"{wt_pct:.6f}",
                    "edited_reads_allowed_only": edited_reads,
                    "edited_pct_allowed_only": f"{edited_pct:.6f}",
                    "disallowed_mut_reads": disallowed_reads,
                    "disallowed_mut_pct": f"{disallowed_pct:.6f}",
                    "same_length_file": str(same_length_file),
                }
            )

            gkey = (condition, target)
            samples_by_group[gkey].append(sid)
            for hap, cnt in case_counts.items():
                pct = (cnt / total_reads * 100.0) if total_reads else 0.0
                case_pct_by_group[gkey][hap][sid] = pct

    case_stat_rows: List[Dict[str, object]] = []
    panel_rows: List[Dict[str, object]] = []
    target_summary_rows: List[Dict[str, object]] = []
    md_lines: List[str] = [
        "# Panel-Like Top Edited Haplotypes (Full Target Conversion Rules)",
        "",
        "Edited case definition:",
        "- Use full target sequence (not short b4-e7 window).",
        "- Keep haplotypes with >=1 allowed conversion and no disallowed substitutions.",
        "- Edited reads (%) = haplotype reads / total same-length reads * 100.",
        "- Markdown output keeps plain haplotype text (no color markup).",
        "",
    ]
    html_sections: List[str] = []

    if skipped_targets:
        md_lines.append("Skipped targets (no conversion rule): " + ", ".join(sorted(skipped_targets)))
        md_lines.append("")

    for gkey, sample_ids_raw in sorted(samples_by_group.items(), key=lambda x: x[0][1]):
        condition, target = gkey
        sample_ids = sorted(set(sample_ids_raw))
        allowed = conversion_rules[target]

        # case stats
        rows_local: List[Dict[str, object]] = []
        for hap in sorted(case_pct_by_group[gkey].keys()):
            vals = [case_pct_by_group[gkey][hap].get(sid, 0.0) for sid in sample_ids]
            mean_v = statistics.mean(vals) if vals else 0.0
            sd_v = statistics.stdev(vals) if len(vals) > 1 else 0.0
            row = {
                "condition": condition,
                "target_seq": target,
                "allowed_conversions": ",".join(f"{a}>{b}" for (a, b) in sorted(allowed)),
                "haplotype": hap,
                "mean_pct": f"{mean_v:.6f}",
                "sd_pct": f"{sd_v:.6f}",
                "n_replicates": len(vals),
                "replicate_values_pct": ",".join(f"{v:.6f}" for v in vals),
                "sample_ids": ",".join(map(str, sample_ids)),
            }
            case_stat_rows.append(row)
            rows_local.append(row)

        rows_local.sort(key=lambda x: float(str(x["mean_pct"])), reverse=True)
        top_rows = rows_local[:20]

        md_lines.append(f"## Condition: {condition} | Target: {target}")
        md_lines.append("Allowed conversions: " + ",".join(f"{a}>{b}" for (a, b) in sorted(allowed)))
        md_lines.append("| Rank | Full-target haplotype | Edited reads (%) |")
        md_lines.append("|---|---|---|")
        for i, rr in enumerate(top_rows, start=1):
            mean_v = float(str(rr["mean_pct"]))
            sd_v = float(str(rr["sd_pct"]))
            decorated = decorate_haplotype_for_md(target, str(rr["haplotype"]), allowed)
            md_lines.append(f"| {i} | {decorated} | {mean_v:.3f} ± {sd_v:.3f} |")
            panel_rows.append(
                {
                    "condition": condition,
                    "target_seq": target,
                    "allowed_conversions": rr["allowed_conversions"],
                    "rank": i,
                    "haplotype": rr["haplotype"],
                    "mean_pct": rr["mean_pct"],
                    "sd_pct": rr["sd_pct"],
                    "n_replicates": rr["n_replicates"],
                    "replicate_values_pct": rr["replicate_values_pct"],
                    "sample_ids": rr["sample_ids"],
                }
            )
        md_lines.append("")

        sec = []
        sec.append(f"<h2>Condition: {condition} | Target: {target}</h2>")
        sec.append("<p>Allowed conversions: " + ",".join(f"{a}&gt;{b}" for (a, b) in sorted(allowed)) + "</p>")
        sec.append("<table>")
        sec.append("<thead><tr><th>Rank</th><th>Full-target haplotype</th><th>Edited reads (%)</th></tr></thead>")
        sec.append("<tbody>")
        for i, rr in enumerate(top_rows, start=1):
            mean_v = float(str(rr["mean_pct"]))
            sd_v = float(str(rr["sd_pct"]))
            decorated = decorate_haplotype_for_html(target, str(rr["haplotype"]), allowed)
            sec.append(
                f"<tr><td>{i}</td><td>{decorated}</td><td>{mean_v:.3f} ± {sd_v:.3f}</td></tr>"
            )
        sec.append("</tbody></table>")
        html_sections.append("\n".join(sec))

        sample_vals = [
            float(str(s["edited_pct_allowed_only"]))
            for s in sample_rows
            if s["condition"] == condition and s["target_seq"] == target
        ]
        mean_total = statistics.mean(sample_vals) if sample_vals else 0.0
        sd_total = statistics.stdev(sample_vals) if len(sample_vals) > 1 else 0.0
        target_summary_rows.append(
            {
                "condition": condition,
                "target_seq": target,
                "allowed_conversions": ",".join(f"{a}>{b}" for (a, b) in sorted(allowed)),
                "n_samples": len(sample_vals),
                "edited_mean_pct_allowed_only": f"{mean_total:.6f}",
                "edited_sd_pct_allowed_only": f"{sd_total:.6f}",
            }
        )

    # main panel outputs
    write_tsv(
        out_tsv,
        panel_rows,
        [
            "condition",
            "target_seq",
            "allowed_conversions",
            "rank",
            "haplotype",
            "mean_pct",
            "sd_pct",
            "n_replicates",
            "replicate_values_pct",
            "sample_ids",
        ],
    )
    out_md.write_text("\n".join(md_lines) + "\n")

    out_html = out_md.with_suffix(".html")
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Panel-Like Top Edited Haplotypes</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      margin: 24px;
      color: #1f1f1f;
      line-height: 1.35;
    }}
    h1 {{ margin-bottom: 8px; }}
    h2 {{ margin-top: 28px; margin-bottom: 8px; }}
    p {{ margin: 6px 0 12px; }}
    table {{
      border-collapse: collapse;
      width: 100%;
      max-width: 1200px;
      margin-bottom: 14px;
    }}
    th, td {{
      border: 1px solid #d9d9d9;
      padding: 6px 8px;
      vertical-align: top;
      font-size: 14px;
    }}
    th {{
      background: #f7f7f7;
      text-align: left;
    }}
    .hap {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
      letter-spacing: 0.2px;
      white-space: nowrap;
    }}
    .edited {{
      color: #d93025;
      font-weight: 700;
    }}
    .note {{
      color: #555;
      font-size: 14px;
      margin-bottom: 12px;
    }}
  </style>
</head>
<body>
  <h1>Panel-Like Top Edited Haplotypes (Full Target Conversion Rules)</h1>
  <div class="note">Allowed edited letters are shown in red.</div>
  {'\\n'.join(html_sections)}
</body>
</html>
"""
    out_html.write_text(html_doc)

    # additional step2 tables
    write_tsv(
        out_tables_dir / "full_target_sample_editing.tsv",
        sample_rows,
        [
            "sample_id",
            "replicate",
            "condition",
            "target_seq",
            "allowed_conversions",
            "total_same_length_reads",
            "wt_reads",
            "wt_pct",
            "edited_reads_allowed_only",
            "edited_pct_allowed_only",
            "disallowed_mut_reads",
            "disallowed_mut_pct",
            "same_length_file",
        ],
    )
    write_tsv(
        out_tables_dir / "full_target_case_stats.tsv",
        case_stat_rows,
        [
            "condition",
            "target_seq",
            "allowed_conversions",
            "haplotype",
            "mean_pct",
            "sd_pct",
            "n_replicates",
            "replicate_values_pct",
            "sample_ids",
        ],
    )
    write_tsv(
        out_tables_dir / "full_target_summary.tsv",
        target_summary_rows,
        [
            "condition",
            "target_seq",
            "allowed_conversions",
            "n_samples",
            "edited_mean_pct_allowed_only",
            "edited_sd_pct_allowed_only",
        ],
    )


def write_tsv(path: Path, rows: List[Dict[str, object]], fields: List[str]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def build_miseq_summary_table(run_rows: List[Dict[str, object]], out_path: Path) -> None:
    rows: List[Dict[str, object]] = []
    for r in run_rows:
        if not bool(r["summary_exists"]):
            continue
        sid = int(r["sample_id"])
        svals = parse_summary_file(Path(str(r["summary_file"])))
        if not svals:
            continue
        rows.append(
            {
                "sample_id": sid,
                "input_file": svals["input_file"],
                "target_seq": svals["target_seq"],
                "window_mutated": svals["window_mutated"],
                "window_total": svals["window_total"],
                "window_ratio": ""
                if svals["window_ratio"] is None
                else f"{float(svals['window_ratio']):.6f}",
                "n_indels": svals["n_indels"],
                "n_all": svals["n_all"],
                "indel_ratio": ""
                if svals["indel_ratio"] is None
                else f"{float(svals['indel_ratio']):.6f}",
            }
        )
    write_tsv(
        out_path,
        rows,
        [
            "sample_id",
            "input_file",
            "target_seq",
            "window_mutated",
            "window_total",
            "window_ratio",
            "n_indels",
            "n_all",
            "indel_ratio",
        ],
    )


def reset_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def link_or_copy_step1_to_step2(step1_dirs: Dict[str, Path], step2_dirs: Dict[str, Path]) -> None:
    # Use symlinks for heavy folders.
    for key in ("merged", "maund_out", "logs"):
        src = step1_dirs[key]
        dst = step2_dirs[key]
        reset_path(dst)
        dst.symlink_to(src)

    # Copy table files so step2 is self-contained.
    for src in step1_dirs["tables"].glob("*.tsv"):
        shutil.copy2(src, step2_dirs["tables"] / src.name)


def parse_id_list(text: str) -> set[int]:
    text = text.strip()
    if not text:
        return set()
    out = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        out.add(int(part))
    return out


def parse_conversion_rules(text: str) -> Dict[str, set[Tuple[str, str]]]:
    """
    Parse conversion rule text.
    Example:
      GCT...:A>G,T>C;GGG...:C>T,G>A
    """
    rules: Dict[str, set[Tuple[str, str]]] = {}
    if not text.strip():
        return rules

    for block in text.split(";"):
        block = block.strip()
        if not block:
            continue
        if ":" not in block:
            raise ValueError(f"Invalid conversion rule block: {block}")
        target, convs = block.split(":", 1)
        target = target.strip().upper()
        pairs: set[Tuple[str, str]] = set()
        for conv in convs.split(","):
            conv = conv.strip().upper()
            if not conv:
                continue
            if ">" not in conv:
                raise ValueError(f"Invalid conversion token: {conv}")
            ref, alt = conv.split(">", 1)
            ref = ref.strip()
            alt = alt.strip()
            if len(ref) != 1 or len(alt) != 1:
                raise ValueError(f"Invalid conversion token: {conv}")
            pairs.add((ref, alt))
        if not pairs:
            raise ValueError(f"No conversion pairs found for target: {target}")
        rules[target] = pairs
    return rules


def parse_key_motif_rules(text: str) -> Dict[str, Tuple[str, str]]:
    """
    Parse key motif rule text.
    Example:
      GCT...:TAT>TGT;GGG...:GCT>GTT
    """
    rules: Dict[str, Tuple[str, str]] = {}
    if not text.strip():
        return rules

    for block in text.split(";"):
        block = block.strip()
        if not block:
            continue
        if ":" not in block:
            raise ValueError(f"Invalid key motif rule block: {block}")
        target, conv = block.split(":", 1)
        target = target.strip().upper()
        conv = conv.strip().upper()
        if ">" not in conv:
            raise ValueError(f"Invalid key motif conversion token: {conv}")
        src, dst = conv.split(">", 1)
        src = src.strip()
        dst = dst.strip()
        if not src or not dst or len(src) != len(dst):
            raise ValueError(f"Invalid key motif conversion token: {conv}")
        rules[target] = (src, dst)
    return rules


def generate_key_motif_tables(
    run_rows: List[Dict[str, object]],
    conversion_rules: Dict[str, set[Tuple[str, str]]],
    key_motif_rules: Dict[str, Tuple[str, str]],
    out_tables_dir: Path,
) -> None:
    per_sample_rows: List[Dict[str, object]] = []
    grouped: Dict[Tuple[str, str, str, str], List[Dict[str, object]]] = defaultdict(list)
    group_hap_any: Dict[Tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)
    group_hap_allowed: Dict[Tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)

    for r in run_rows:
        if int(r["return_code"]) != 0:
            continue
        if not bool(r["same_length_exists"]):
            continue
        target = str(r["rgen"]).upper()
        if target not in key_motif_rules:
            continue

        motif_src, motif_dst = key_motif_rules[target]
        allowed = conversion_rules.get(target, set())
        sid = int(r["sample_id"])
        condition = str(r["condition"])
        aseq = str(r["aseq"]).upper()
        same_length_file = Path(str(r["same_length_file"]))
        idx = target_index_in_fragment(aseq, target)
        tlen = len(target)

        total_reads = 0
        motif_any_reads = 0
        motif_allowed_reads = 0

        with same_length_file.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                seq = parts[0].strip().upper()
                n = int(parts[1])
                if len(seq) < idx + tlen:
                    continue
                hap = seq[idx : idx + tlen]
                total_reads += n

                if has_motif_conversion(target, hap, motif_src, motif_dst):
                    motif_any_reads += n
                    group_hap_any[(condition, target, motif_src, motif_dst)][hap] += n
                    if allowed and is_allowed_only_haplotype(target, hap, allowed):
                        motif_allowed_reads += n
                        group_hap_allowed[(condition, target, motif_src, motif_dst)][hap] += n

        row = {
            "sample_id": sid,
            "replicate": r["replicate"],
            "condition": condition,
            "target_seq": target,
            "key_motif_source": motif_src,
            "key_motif_dest": motif_dst,
            "allowed_conversions": ",".join(f"{a}>{b}" for (a, b) in sorted(allowed)),
            "total_same_length_reads": total_reads,
            "key_motif_any_reads": motif_any_reads,
            "key_motif_any_pct": f"{(motif_any_reads / total_reads * 100.0) if total_reads else 0.0:.6f}",
            "key_motif_allowed_only_reads": motif_allowed_reads,
            "key_motif_allowed_only_pct": f"{(motif_allowed_reads / total_reads * 100.0) if total_reads else 0.0:.6f}",
            "sample_key_motif_any_success": "True" if motif_any_reads > 0 else "False",
            "sample_key_motif_allowed_only_success": "True" if motif_allowed_reads > 0 else "False",
            "same_length_file": str(same_length_file),
        }
        per_sample_rows.append(row)
        grouped[(condition, target, motif_src, motif_dst)].append(row)

    summary_rows: List[Dict[str, object]] = []
    for (condition, target, motif_src, motif_dst), rows in sorted(grouped.items(), key=lambda x: x[0][1]):
        gkey = (condition, target, motif_src, motif_dst)
        hap_any_counter = group_hap_any[gkey]
        hap_allowed_counter = group_hap_allowed[gkey]
        top_any = hap_any_counter.most_common(1)
        top_allowed = hap_allowed_counter.most_common(1)

        total_reads = sum(int(r["total_same_length_reads"]) for r in rows)
        motif_any = sum(int(r["key_motif_any_reads"]) for r in rows)
        motif_allowed = sum(int(r["key_motif_allowed_only_reads"]) for r in rows)
        any_success_ids = [int(r["sample_id"]) for r in rows if str(r["sample_key_motif_any_success"]) == "True"]
        allowed_success_ids = [
            int(r["sample_id"]) for r in rows if str(r["sample_key_motif_allowed_only_success"]) == "True"
        ]

        summary_rows.append(
            {
                "condition": condition,
                "target_seq": target,
                "key_motif_source": motif_src,
                "key_motif_dest": motif_dst,
                "n_samples": len(rows),
                "samples_with_key_motif_any": len(any_success_ids),
                "samples_with_key_motif_allowed_only": len(allowed_success_ids),
                "sample_ids_with_key_motif_any": ",".join(map(str, sorted(any_success_ids))),
                "sample_ids_with_key_motif_allowed_only": ",".join(map(str, sorted(allowed_success_ids))),
                "total_same_length_reads": total_reads,
                "key_motif_any_reads": motif_any,
                "key_motif_any_pct": f"{(motif_any / total_reads * 100.0) if total_reads else 0.0:.6f}",
                "unique_key_motif_haplotypes_any": len(hap_any_counter),
                "top_key_motif_haplotype_any": "" if not top_any else top_any[0][0],
                "top_key_motif_haplotype_any_reads": 0 if not top_any else top_any[0][1],
                "key_motif_allowed_only_reads": motif_allowed,
                "key_motif_allowed_only_pct": f"{(motif_allowed / total_reads * 100.0) if total_reads else 0.0:.6f}",
                "unique_key_motif_haplotypes_allowed_only": len(hap_allowed_counter),
                "top_key_motif_haplotype_allowed_only": "" if not top_allowed else top_allowed[0][0],
                "top_key_motif_haplotype_allowed_only_reads": 0 if not top_allowed else top_allowed[0][1],
            }
        )

    write_tsv(
        out_tables_dir / "key_motif_per_sample.tsv",
        per_sample_rows,
        [
            "sample_id",
            "replicate",
            "condition",
            "target_seq",
            "key_motif_source",
            "key_motif_dest",
            "allowed_conversions",
            "total_same_length_reads",
            "key_motif_any_reads",
            "key_motif_any_pct",
            "key_motif_allowed_only_reads",
            "key_motif_allowed_only_pct",
            "sample_key_motif_any_success",
            "sample_key_motif_allowed_only_success",
            "same_length_file",
        ],
    )
    write_tsv(
        out_tables_dir / "key_motif_summary.tsv",
        summary_rows,
        [
            "condition",
            "target_seq",
            "key_motif_source",
            "key_motif_dest",
            "n_samples",
            "samples_with_key_motif_any",
            "samples_with_key_motif_allowed_only",
            "sample_ids_with_key_motif_any",
            "sample_ids_with_key_motif_allowed_only",
            "total_same_length_reads",
            "key_motif_any_reads",
            "key_motif_any_pct",
            "unique_key_motif_haplotypes_any",
            "top_key_motif_haplotype_any",
            "top_key_motif_haplotype_any_reads",
            "key_motif_allowed_only_reads",
            "key_motif_allowed_only_pct",
            "unique_key_motif_haplotypes_allowed_only",
            "top_key_motif_haplotype_allowed_only",
            "top_key_motif_haplotype_allowed_only_reads",
        ],
    )


def main() -> None:
    args = parse_args()
    conversion_rules = parse_conversion_rules(args.conversion_rules)
    key_motif_rules = parse_key_motif_rules(args.key_motif_rules)

    fastq_dir = Path(args.fastq_dir)
    seq_xlsx = Path(args.seq_xlsx)
    base_dir = Path(args.base_dir)
    maund_home = Path(args.maund_home)
    python_bin = maund_home / ".venv2/bin/python"
    if not python_bin.exists():
        raise RuntimeError(f"Python binary not found: {python_bin}")

    step1_root = base_dir / f"maund_{args.date_tag}"
    step2_root = base_dir / f"maund_{args.date_tag}_2"
    step1_dirs = setup_work_dirs(step1_root)
    step2_dirs = setup_work_dirs(step2_root)

    mapping = parse_xlsx_mapping(seq_xlsx)
    pairs = discover_fastq_pairs(fastq_dir)

    excluded = parse_id_list(args.exclude_samples)
    only_ids = parse_id_list(args.sample_ids)

    all_pair_ids = set(pairs.keys())
    selected = {sid for sid in all_pair_ids if sid in mapping and sid not in excluded}
    if only_ids:
        selected &= only_ids
    selected_ids = sorted(selected)

    merge_rows = merge_samples(selected_ids, pairs, step1_dirs["merged"], args.offset)
    run_rows = run_maund(
        selected_ids,
        mapping,
        pairs,
        step1_dirs["merged"],
        step1_dirs["maund_out"],
        step1_dirs["logs"],
        maund_home,
        python_bin,
        args.otag,
        args.condition,
    )
    edited_rows = compute_edited_reads(run_rows)
    csum = condition_summary(edited_rows, args.condition)

    # Step1 tables
    mapping_rows = [
        {
            "sample_id": sid,
            "s_index": pairs[sid]["s_index"],
            "aseq": mapping[sid]["aseq"],
            "rgen": mapping[sid]["rgen"],
        }
        for sid in selected_ids
    ]
    skipped_rows = []
    for sid in sorted(all_pair_ids):
        if sid in excluded:
            skipped_rows.append({"sample_id": sid, "reason": "excluded_by_user"})
        elif sid not in mapping:
            skipped_rows.append({"sample_id": sid, "reason": "no_sequence_mapping_in_xlsx"})
        elif only_ids and sid not in only_ids:
            skipped_rows.append({"sample_id": sid, "reason": "not_in_sample_ids_filter"})

    write_tsv(
        step1_dirs["tables"] / "sample_mapping_used.tsv",
        mapping_rows,
        ["sample_id", "s_index", "aseq", "rgen"],
    )
    write_tsv(
        step1_dirs["tables"] / "merge_stats.tsv",
        merge_rows,
        ["sample_id", "s_index", "read_count", "offset", "overlap_match_ratio", "merged_fastq"],
    )
    write_tsv(
        step1_dirs["tables"] / "run_status.tsv",
        run_rows,
        [
            "sample_id",
            "replicate",
            "condition",
            "s_index",
            "aseq",
            "rgen",
            "return_code",
            "summary_file",
            "summary_exists",
            "window_file",
            "window_exists",
            "same_length_file",
            "same_length_exists",
            "log_file",
        ],
    )
    write_tsv(step1_dirs["tables"] / "skipped_samples.tsv", skipped_rows, ["sample_id", "reason"])
    write_tsv(
        step1_dirs["tables"] / "edited_reads.tsv",
        edited_rows,
        [
            "sample_id",
            "replicate",
            "condition",
            "s_index",
            "target_window_ref",
            "window_total_reads",
            "window_wt_reads",
            "edited_reads_percent",
            "maund_window_mutated",
            "maund_window_total",
            "maund_window_ratio",
            "maund_n_indels",
            "maund_n_all",
            "maund_indel_ratio",
        ],
    )
    write_tsv(
        step1_dirs["tables"] / "condition_summary.tsv",
        [csum],
        ["condition", "n_samples", "edited_reads_mean_percent", "edited_reads_sd_percent"],
    )
    build_miseq_summary_table(run_rows, step1_dirs["tables"] / "maund_miseq_summary.tsv")

    # Step2 setup + panel-like outputs
    link_or_copy_step1_to_step2(step1_dirs, step2_dirs)
    generate_panel_like_tables(
        run_rows,
        step2_dirs["tables"] / "panel_like_top_haplotypes.tsv",
        step2_dirs["tables"] / "panel_like_top_haplotypes.md",
        conversion_rules,
        step2_dirs["tables"],
    )
    generate_key_motif_tables(run_rows, conversion_rules, key_motif_rules, step2_dirs["tables"])

    summary = [
        f"step1: {step1_root}",
        f"step2: {step2_root}",
        f"selected_samples: {len(selected_ids)}",
        f"skipped_samples: {len(skipped_rows)}",
    ]
    print("\n".join(summary))


if __name__ == "__main__":
    main()
