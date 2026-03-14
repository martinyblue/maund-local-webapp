from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable


COMPARISON_RANGE = 60
FILTER_MIN_COUNT = 1
WINDOW_BEG = 4
WINDOW_END = 7
IDXSEQ_BEG = 13
IDXSEQ_END = 22
TRANS = str.maketrans("ATGCN", "TACGN")


def revcomp(seq: str) -> str:
    return seq.translate(TRANS)[::-1]


def mismatch(seq1: str, seq2: str) -> int:
    n = min(len(seq1), len(seq2))
    m = max(len(seq1), len(seq2))
    return sum(1 for a, b in zip(seq1[:n], seq2[:n]) if a != b) + (m - n)


def match_upto1(target: str, seq: str) -> int:
    half = len(target) // 2
    fst = target[:half]
    snd = target[half:]

    idx = seq.find(fst)
    while idx != -1:
        beg = idx
        end = beg + len(target)
        if mismatch(seq[beg:end], target) < 2:
            return beg
        idx = seq.find(fst, end)

    idx = seq.find(snd)
    while idx != -1:
        beg = idx - half
        end = beg + len(target)
        if mismatch(seq[beg:end], target) < 2:
            return beg
        idx = seq.find(snd, end)
    return -1


def iter_fastq_sequences(path: Path) -> Iterable[str]:
    with path.open() as handle:
        while True:
            header = handle.readline()
            if not header:
                break
            yield handle.readline().strip().upper()
            handle.readline()
            handle.readline()


def write_counter_with_len(path: Path, counter: Counter[str]) -> None:
    with path.open("w") as handle:
        for seq, count in counter.most_common():
            handle.write(f"{seq}\t{count}\t{len(seq)}\n")


def run_single_sample_lite(
    *,
    sample_id: int,
    merged_path: Path,
    aseq: str,
    target: str,
    maund_out_dir: Path,
    logs_dir: Path,
    condition: str,
    replicate: int,
    s_index: int,
    otag: str,
) -> dict[str, object]:
    log_file = logs_dir / f"{sample_id}.log"
    out_name = f"{merged_path.name}.{target}.maund.{otag}."
    summary_file = maund_out_dir / f"{out_name}Miseq_summary.txt"
    window_file = maund_out_dir / f"{out_name}_window.txt"
    same_length_file = maund_out_dir / f"{out_name}_same_length.txt"
    all_file = maund_out_dir / f"{out_name}_all.txt"
    mut_file = maund_out_dir / f"{out_name}_mut.txt"
    wt_subst_file = maund_out_dir / f"{out_name}_WT_subst.txt"

    amplicon = aseq.upper()
    rgen = target.upper()
    target_idx = amplicon.find(rgen)
    if target_idx == -1:
        raise RuntimeError(f"Target not found in amplicon for sample {sample_id}: {rgen}")

    idx_cleavage = len(rgen) - 6
    start_pos = max(0, target_idx + idx_cleavage - COMPARISON_RANGE)
    end_pos = min(len(amplicon), target_idx + idx_cleavage + COMPARISON_RANGE)
    seq_range = amplicon[start_pos:end_pos]
    length_range = len(seq_range)
    pri_for = seq_range[:15]
    pri_back = seq_range[-15:]

    i_rgen = seq_range.find(rgen)
    if i_rgen == -1:
        raise RuntimeError(f"Target not found in comparison range for sample {sample_id}")

    w_beg = i_rgen + (WINDOW_BEG - 1)
    w_end = i_rgen + WINDOW_END
    wt_window = seq_range[w_beg:w_end]
    index_beg = i_rgen + (IDXSEQ_BEG - 1)
    index_end = i_rgen + IDXSEQ_END
    index_seq = seq_range[index_beg:index_end]

    extracted: Counter[str] = Counter()
    for seq in iter_fastq_sequences(merged_path):
        if "N" in seq:
            continue
        i_beg = match_upto1(pri_for, seq)
        if i_beg == -1:
            continue
        i_end = match_upto1(pri_back, seq)
        if i_end == -1 or i_beg >= i_end:
            continue
        frag = seq[i_beg : i_end + len(pri_back)]
        extracted[frag] += 1

    all_counter = Counter({seq: n for seq, n in extracted.items() if n > FILTER_MIN_COUNT})
    same_len_counter = Counter({seq: n for seq, n in all_counter.items() if len(seq) == length_range})
    mut_counter = Counter({seq: n for seq, n in all_counter.items() if (rgen not in seq) and len(seq) != length_range})
    wt_subst_counter = Counter(
        {seq: n for seq, n in all_counter.items() if (rgen not in seq) and len(seq) == length_range}
    )

    write_counter_with_len(all_file, all_counter)
    write_counter_with_len(mut_file, mut_counter)
    write_counter_with_len(wt_subst_file, wt_subst_counter)
    write_counter_with_len(same_length_file, same_len_counter)

    window_counter: Counter[str] = Counter()
    for seq, count in same_len_counter.items():
        if len(seq) >= w_end:
            window_counter[seq[w_beg:w_end]] += count
    with window_file.open("w") as handle:
        handle.write("window\tn_seq\n")
        for window, count in window_counter.most_common():
            handle.write(f"{window}\t{count}\n")

    window_total = sum(window_counter.values())
    window_mutated = window_total - window_counter.get(wt_window, 0)
    n_all = sum(all_counter.values())
    n_indels = sum(n for seq, n in all_counter.items() if (index_seq not in seq) and len(seq) != length_range)
    window_ratio = (window_mutated / window_total) if window_total else float("nan")
    indel_ratio = (n_indels / n_all) if n_all else float("nan")

    with summary_file.open("w") as handle:
        handle.write(
            "{}\t{}\t{}\t{}\t{:.4f}\t{}\t{}\t{:.4f}\n".format(
                merged_path.name,
                rgen,
                window_mutated,
                window_total,
                window_ratio,
                n_indels,
                n_all,
                indel_ratio,
            )
        )

    log_file.write_text(
        "\n".join(
            [
                f"sample_id={sample_id}",
                "mode=maund_lite",
                f"target={rgen}",
                f"length_range={length_range}",
                f"all_reads={n_all}",
                f"same_length_reads={sum(same_len_counter.values())}",
                f"window_total={window_total}",
            ]
        )
        + "\n"
    )

    return {
        "sample_id": sample_id,
        "replicate": replicate,
        "condition": condition,
        "s_index": s_index,
        "aseq": amplicon,
        "rgen": rgen,
        "return_code": 0,
        "summary_file": str(summary_file),
        "summary_exists": summary_file.exists(),
        "window_file": str(window_file),
        "window_exists": window_file.exists(),
        "same_length_file": str(same_length_file),
        "same_length_exists": same_length_file.exists(),
        "log_file": str(log_file),
    }


def run_maund_lite(
    *,
    sample_ids: list[int],
    seq_map: dict[int, dict[str, str]],
    pairs: dict[int, dict[str, object]],
    merged_dir: Path,
    maund_out_dir: Path,
    logs_dir: Path,
    condition: str,
    otag: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for replicate, sample_id in enumerate(sorted(sample_ids), start=1):
        rows.append(
            run_single_sample_lite(
                sample_id=sample_id,
                merged_path=merged_dir / f"{sample_id}.merged.fastq",
                aseq=seq_map[sample_id]["sequence"],
                target=seq_map[sample_id]["target_window"],
                maund_out_dir=maund_out_dir,
                logs_dir=logs_dir,
                condition=condition,
                replicate=replicate,
                s_index=int(pairs[sample_id]["s_index"]),
                otag=otag,
            )
        )
    return rows
