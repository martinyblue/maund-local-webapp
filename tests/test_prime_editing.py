from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from maund_local_app.engine import run_analysis, validate_config
from maund_local_app.io_utils import infer_flat_blocks
from maund_local_app.models import AnalysisConfig
from maund_local_app.prime_editing import (
    build_prime_sample_reports,
    intended_positions_map,
    validate_prime_desired_products,
)
from maund_workflow.run_pipeline import discover_fastq_pairs


DOWNLOADS = Path(os.environ.get("MAUND_TEST_INPUT_DIR", str(Path.home() / "Downloads")))
PRIME_TARGET = "ACATTTCTTCCTAGCTGCTTGGCCTGT"
PRIME_DESIRED = "ACATTTCGTCCTAGCTGCTTGGCCTGT"


class PrimeEditingUnitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="maund_prime_test_", dir="/tmp"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_intended_positions_map_identifies_single_substitution(self) -> None:
        self.assertEqual(intended_positions_map(PRIME_TARGET, (PRIME_DESIRED,)), {8: "G"})

    def test_validate_prime_desired_products_rejects_length_change(self) -> None:
        with self.assertRaises(ValueError):
            validate_prime_desired_products(PRIME_TARGET, (PRIME_TARGET + "A",))

    def test_build_prime_sample_reports_classifies_outcomes(self) -> None:
        exact = PRIME_DESIRED
        intended_plus_extra = PRIME_DESIRED[:15] + "A" + PRIME_DESIRED[16:]
        other_sub = PRIME_TARGET[:7] + "A" + PRIME_TARGET[8:]
        scaffold_fragment = "GGGGGGGG"
        indel_fragment = "ACATTTCTTCCTA"

        same_length_file = self.tmp_dir / "same_length.txt"
        same_length_file.write_text(
            "\n".join(
                [
                    f"{PRIME_TARGET}\t50",
                    f"{exact}\t10",
                    f"{intended_plus_extra}\t5",
                    f"{other_sub}\t3",
                ]
            )
            + "\n"
        )
        all_file = self.tmp_dir / "all.txt"
        all_file.write_text(
            "\n".join(
                [
                    f"{PRIME_TARGET}\t50",
                    f"{exact}\t10",
                    f"{intended_plus_extra}\t5",
                    f"{other_sub}\t3",
                    f"{scaffold_fragment}\t2",
                    f"{indel_fragment}\t4",
                ]
            )
            + "\n"
        )

        per_sample_rows, allele_rows, scaffold_rows = build_prime_sample_reports(
            run_rows=[
                {
                    "sample_id": 94,
                    "replicate": 1,
                    "condition": "one_condition",
                    "s_index": 94,
                    "return_code": 0,
                    "rgen": PRIME_TARGET,
                    "same_length_exists": True,
                    "same_length_file": str(same_length_file),
                    "all_file": str(all_file),
                    "comparison_length": len(PRIME_TARGET),
                    "target_index_in_fragment": 0,
                    "all_read_count": 74,
                    "same_length_read_count": 68,
                }
            ],
            desired_products=(PRIME_DESIRED,),
            scaffold_sequence="GGGGGGGG",
        )

        self.assertEqual(len(per_sample_rows), 1)
        row = per_sample_rows[0]
        self.assertEqual(row["wt_reads"], 50)
        self.assertEqual(row["exact_intended_reads"], 10)
        self.assertEqual(row["intended_plus_extra_reads"], 5)
        self.assertEqual(row["other_substitution_byproduct_reads"], 3)
        self.assertEqual(row["scaffold_derived_reads"], 2)
        self.assertEqual(row["indel_only_reads"], 4)
        self.assertEqual(row["prime_edited_total_reads"], 15)
        self.assertEqual(row["edit_to_indel_ratio"], "3.750000")
        self.assertEqual(len(scaffold_rows), 1)
        allele_classes = {allele["allele_class"] for allele in allele_rows}
        self.assertIn("exact_intended", allele_classes)
        self.assertIn("intended_plus_extra", allele_classes)
        self.assertIn("other_substitution_byproduct", allele_classes)
        self.assertIn("indel_only", allele_classes)


class PrimeEditingIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="maund_prime_integration_", dir="/tmp"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _assert_external_inputs(self, *paths: Path) -> None:
        for path in paths:
            if not path.exists():
                self.skipTest(f"Missing input: {path}")

    def _prime_fastq_dir(self) -> Path:
        candidates = [
            DOWNLOADS / "260325_prime_editing",
            DOWNLOADS / "조상원 (11)",
            DOWNLOADS / "조상원 (1)",
            DOWNLOADS,
        ]
        for candidate in candidates:
            if not candidate.exists():
                continue
            pairs = discover_fastq_pairs(candidate)
            if {94, 95, 96}.issubset(set(pairs)):
                return candidate
        self.skipTest("Missing FASTQ directory containing sample IDs 94, 95, 96")

    def test_infer_flat_blocks_reads_prime_sheet(self) -> None:
        seq_xlsx = DOWNLOADS / "prime editing seq.xlsx"
        self._assert_external_inputs(seq_xlsx)
        blocks = infer_flat_blocks(seq_xlsx, default_desired_products=(PRIME_DESIRED,))
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].sample_ids, (94, 95, 96))
        self.assertEqual([label for label, _ in blocks[0].row_items], ["control2", "ELVd2", "ELVd3"])

    def test_validate_prime_heatmap_accepts_flat_xlsx(self) -> None:
        fastq_dir = self._prime_fastq_dir()
        seq_xlsx = DOWNLOADS / "prime editing seq.xlsx"
        self._assert_external_inputs(fastq_dir, seq_xlsx)

        config = AnalysisConfig(
            fastq_dir=fastq_dir,
            seq_xlsx=seq_xlsx,
            editor_type="prime",
            desired_products=(PRIME_DESIRED,),
            analysis_mode="block_heatmap",
            output_base_dir=self.tmp_dir,
        )
        validation = validate_config(config)
        self.assertTrue(validation.is_valid, msg="\n".join(validation.errors))
        self.assertEqual(len(validation.detected_blocks), 1)
        self.assertEqual(validation.detected_blocks[0].sample_ids, (94, 95, 96))

    def test_prime_single_target_run_generates_prime_outputs(self) -> None:
        fastq_dir = self._prime_fastq_dir()
        seq_xlsx = DOWNLOADS / "prime editing seq.xlsx"
        self._assert_external_inputs(fastq_dir, seq_xlsx)

        config = AnalysisConfig(
            fastq_dir=fastq_dir,
            seq_xlsx=seq_xlsx,
            sample_ids=(94, 95, 96),
            target_seq=PRIME_TARGET,
            editor_type="prime",
            desired_products=(PRIME_DESIRED,),
            analysis_mode="single_target",
            date_tag="990325_101010",
            output_base_dir=self.tmp_dir,
        )
        result = run_analysis(config)
        self.assertTrue(result.key_output_paths["per_sample_editing"].exists())
        self.assertTrue(result.key_output_paths["prime_allele_classes"].exists())
        self.assertTrue(result.key_output_paths["html_report"].exists())
        self.assertTrue(result.key_output_paths["heatmap_matrix"].exists())
        html = result.key_output_paths["html_report"].read_text()
        self.assertIn("Position Heatmap", html)
        self.assertIn("8&rarr;G", html)

    def test_prime_heatmap_run_generates_inferred_block_report(self) -> None:
        fastq_dir = self._prime_fastq_dir()
        seq_xlsx = DOWNLOADS / "prime editing seq.xlsx"
        self._assert_external_inputs(fastq_dir, seq_xlsx)

        config = AnalysisConfig(
            fastq_dir=fastq_dir,
            seq_xlsx=seq_xlsx,
            editor_type="prime",
            desired_products=(PRIME_DESIRED,),
            analysis_mode="block_heatmap",
            date_tag="990325_111111",
            output_base_dir=self.tmp_dir,
        )
        result = run_analysis(config)
        report_keys = [key for key in result.key_output_paths if key.startswith("report_")]
        self.assertEqual(len(report_keys), 1)
        report_path = result.key_output_paths[report_keys[0]]
        self.assertTrue(report_path.exists())
        html = report_path.read_text()
        self.assertIn("Position Heatmap", html)
        self.assertIn("control2", html)
        self.assertIn("ELVd2", html)
        self.assertIn("ELVd3", html)
        self.assertIn("&rarr;G", html)


if __name__ == "__main__":
    unittest.main()
