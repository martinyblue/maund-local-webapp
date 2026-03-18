from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from maund_local_app.engine import run_analysis, validate_config
from maund_local_app.io_utils import load_block_specs, load_seq_mappings, parse_id_spec, read_tsv
from maund_local_app.models import AnalysisConfig, default_date_tag
from maund_workflow.run_pipeline import discover_fastq_pairs


DOWNLOADS = Path(os.environ.get("MAUND_TEST_INPUT_DIR", str(Path.home() / "Downloads")))


class ParseHelpersTest(unittest.TestCase):
    def test_parse_id_spec_supports_ranges(self) -> None:
        self.assertEqual(parse_id_spec("71,72,75-77,80~81"), (71, 72, 75, 76, 77, 80, 81))

    def test_parse_id_spec_supports_annotated_single_ids(self) -> None:
        self.assertEqual(parse_id_spec("68(wild type)"), (68,))
        self.assertEqual(parse_id_spec("68 (WT)"), (68,))
        self.assertEqual(parse_id_spec("68-wt"), (68,))

    def test_default_date_tag_uses_date_and_time(self) -> None:
        tag = default_date_tag()
        self.assertRegex(tag, r"^\d{6}_\d{6}$")

    def test_load_seq_mappings_supports_legacy_sheet_layout(self) -> None:
        legacy_xlsx = DOWNLOADS / "seq정보.xlsx"
        if not legacy_xlsx.exists():
            self.skipTest(f"Missing input: {legacy_xlsx}")
        seq_map = load_seq_mappings(legacy_xlsx)
        self.assertIn(71, seq_map)
        self.assertEqual(seq_map[71]["target_window"], "GCTCACGGTTATTTTGGCCGAT")

    def test_load_block_specs_detects_multi_block_sheet(self) -> None:
        block_xlsx = DOWNLOADS / "seq정보 to 동현 260313.xlsx"
        if not block_xlsx.exists():
            self.skipTest(f"Missing input: {block_xlsx}")
        blocks = load_block_specs(block_xlsx)
        self.assertEqual([block.display_name for block in blocks], ["N234", "F260"])
        self.assertEqual(blocks[0].sample_ids[0], 49)
        self.assertEqual(blocks[0].sample_ids[-1], 67)
        self.assertEqual(blocks[1].sample_ids[0], 74)
        self.assertEqual(blocks[1].sample_ids[-1], 96)
        self.assertNotIn(68, blocks[0].sample_ids)

    def test_load_seq_mappings_supports_annotated_flat_sheet_layout(self) -> None:
        annotated_xlsx = DOWNLOADS / "seq정보_260315.xlsx"
        if not annotated_xlsx.exists():
            self.skipTest(f"Missing input: {annotated_xlsx}")
        seq_map = load_seq_mappings(annotated_xlsx)
        self.assertEqual(tuple(sorted(seq_map)), (68,))
        self.assertEqual(seq_map[68]["target_window"], "GCTCACGGTTATTTTGGCCGAT")


class ValidationTest(unittest.TestCase):
    def test_validate_config_reports_target_absence(self) -> None:
        config = AnalysisConfig(
            fastq_dir=DOWNLOADS / "조상원 (6)",
            seq_xlsx=DOWNLOADS / "seq정보.xlsx",
            target_seq="CCCCCCCCCCCCCCCCCCCC",
            editor_type="taled",
            sample_ids=(71,),
            output_base_dir=Path("/tmp"),
        )
        result = validate_config(config)
        self.assertFalse(result.is_valid)
        self.assertIn(71, result.invalid_target_sample_ids)


class RegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="maund_local_app_test_", dir="/tmp"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _assert_external_inputs(self, *paths: Path) -> None:
        for path in paths:
            if not path.exists():
                self.skipTest(f"Missing input: {path}")

    def test_regression_260308_style(self) -> None:
        fastq_dir = DOWNLOADS
        seq_xlsx = DOWNLOADS / "seq정보 to 동현.xlsx"
        sample_tale_xlsx = DOWNLOADS / "sample id+ TALE.xlsx"
        tale_array_xlsx = DOWNLOADS / "TALE-array-Golden Gate assembly (조박사님) arabidopsis.xlsx"
        golden_path = Path("maund_260308/tables/gct_target_or_ag_tc_per_sample_with_modules_260308.tsv")
        self._assert_external_inputs(fastq_dir, seq_xlsx, sample_tale_xlsx, tale_array_xlsx, golden_path)

        config = AnalysisConfig(
            fastq_dir=fastq_dir,
            seq_xlsx=seq_xlsx,
            sample_tale_xlsx=sample_tale_xlsx,
            tale_array_xlsx=tale_array_xlsx,
            sample_ids=(93, 94, 95),
            target_seq="AAATGAATCTGCTAATGAA",
            editor_type="taled",
            date_tag="990308",
            output_base_dir=self.tmp_dir,
        )
        result = run_analysis(config)
        out_rows = read_tsv(result.key_output_paths["per_sample_editing"])
        golden_rows = read_tsv(golden_path)

        actual = {
            int(row["sample_id"]): row["edited_pct_allowed_only"]
            for row in out_rows
        }
        golden = {
            int(row["sample_id"]): row["edited_pct_or_allowed"]
            for row in golden_rows
        }
        self.assertEqual(actual, golden)

    def test_block_heatmap_validation_detects_blocks(self) -> None:
        fastq_dir = DOWNLOADS / "조상원 (11)"
        seq_xlsx = DOWNLOADS / "seq정보 to 동현 260313.xlsx"
        self._assert_external_inputs(fastq_dir, seq_xlsx)

        config = AnalysisConfig(
            fastq_dir=fastq_dir,
            seq_xlsx=seq_xlsx,
            editor_type="taled",
            analysis_mode="block_heatmap",
            output_base_dir=self.tmp_dir,
        )
        validation = validate_config(config)
        self.assertTrue(validation.is_valid, msg="\n".join(validation.errors))
        self.assertEqual([block.display_name for block in validation.detected_blocks], ["N234", "F260"])
        self.assertIn(49, validation.selected_sample_ids)
        self.assertIn(96, validation.selected_sample_ids)
        self.assertNotIn(68, validation.selected_sample_ids)

    def test_block_heatmap_run_creates_block_specific_outputs(self) -> None:
        fastq_dir = DOWNLOADS / "조상원 (11)"
        seq_xlsx = DOWNLOADS / "seq정보 to 동현 260313.xlsx"
        sample_tale_xlsx = DOWNLOADS / "sample id+ TALE.xlsx"
        tale_array_xlsx = DOWNLOADS / "TALE-array-Golden Gate assembly (조박사님) arabidopsis.xlsx"
        self._assert_external_inputs(fastq_dir, seq_xlsx, sample_tale_xlsx, tale_array_xlsx)

        config = AnalysisConfig(
            fastq_dir=fastq_dir,
            seq_xlsx=seq_xlsx,
            sample_tale_xlsx=sample_tale_xlsx,
            tale_array_xlsx=tale_array_xlsx,
            editor_type="taled",
            analysis_mode="block_heatmap",
            heatmap_color_max_pct=100.0,
            sample_ids=(49, 67, 74, 82),
            date_tag="991315_120000",
            output_base_dir=self.tmp_dir,
        )
        result = run_analysis(config)

        run_dir_name = result.run_dir.name
        self.assertEqual(run_dir_name, "maund_991315_120000")
        self.assertIn("report_n234", result.key_output_paths)
        self.assertIn("report_f260", result.key_output_paths)
        self.assertTrue(result.key_output_paths["report_n234"].exists())
        self.assertTrue(result.key_output_paths["report_f260"].exists())
        self.assertTrue(result.key_output_paths["heatmap_matrix_n234"].exists())
        self.assertTrue(result.key_output_paths["heatmap_matrix_f260"].exists())

        html_text = result.key_output_paths["report_n234"].read_text()
        self.assertIn("Position Heatmap", html_text)
        self.assertIn("Per-sample Editing Summary", html_text)
        self.assertIn("Haplotype Cards", html_text)
        self.assertIn("0-100%", html_text)

        heatmap_rows = read_tsv(result.key_output_paths["heatmap_matrix_n234"])
        self.assertEqual([int(row["sample_id"]) for row in heatmap_rows], [49, 67])
        self.assertTrue(any(key.startswith("pos_14") for key in heatmap_rows[0].keys()))

    def test_validate_config_supports_annotated_single_target_sheet(self) -> None:
        fastq_dir = DOWNLOADS / "조상원 (11)"
        seq_xlsx = DOWNLOADS / "seq정보_260315.xlsx"
        self._assert_external_inputs(fastq_dir, seq_xlsx)

        config = AnalysisConfig(
            fastq_dir=fastq_dir,
            seq_xlsx=seq_xlsx,
            sample_ids=(68,),
            target_seq="GCTCACGGTTATTTTGGCCGAT",
            editor_type="taled",
            analysis_mode="single_target",
            output_base_dir=self.tmp_dir,
        )
        validation = validate_config(config)
        self.assertTrue(validation.is_valid, msg="\n".join(validation.errors))
        self.assertEqual(validation.selected_sample_ids, (68,))

    def test_single_target_run_for_sample_68_creates_expected_outputs(self) -> None:
        fastq_dir = DOWNLOADS / "조상원 (11)"
        seq_xlsx = DOWNLOADS / "seq정보_260315.xlsx"
        sample_tale_xlsx = DOWNLOADS / "sample id+ TALE.xlsx"
        tale_array_xlsx = DOWNLOADS / "TALE-array-Golden Gate assembly (조박사님) arabidopsis.xlsx"
        self._assert_external_inputs(fastq_dir, seq_xlsx, sample_tale_xlsx, tale_array_xlsx)

        config = AnalysisConfig(
            fastq_dir=fastq_dir,
            seq_xlsx=seq_xlsx,
            sample_tale_xlsx=sample_tale_xlsx,
            tale_array_xlsx=tale_array_xlsx,
            sample_ids=(68,),
            target_seq="GCTCACGGTTATTTTGGCCGAT",
            editor_type="taled",
            analysis_mode="single_target",
            date_tag="991315_130000",
            output_base_dir=self.tmp_dir,
        )
        result = run_analysis(config)

        self.assertEqual(result.run_dir.name, "maund_991315_130000")
        self.assertIn("per_sample_editing", result.key_output_paths)
        self.assertIn("html_report", result.key_output_paths)
        self.assertTrue(result.key_output_paths["per_sample_editing"].exists())
        self.assertTrue(result.key_output_paths["html_report"].exists())
        self.assertNotIn("report_n234", result.key_output_paths)
        self.assertTrue(
            any("Tail mapping missing for selected sample IDs: 68" in warning for warning in result.warnings),
            msg=str(result.warnings),
        )

    def test_regression_260304_style(self) -> None:
        fastq_dir = DOWNLOADS / "조상원 (6)"
        seq_xlsx = DOWNLOADS / "seq정보.xlsx"
        sample_tale_xlsx = DOWNLOADS / "sample id+ TALE.xlsx"
        tale_array_xlsx = DOWNLOADS / "TALE-array-Golden Gate assembly (조박사님) arabidopsis.xlsx"
        golden_path = Path("maund_260304/tables/gct_target_71_85_or_ag_tc_per_sample_with_modules_260304.tsv")
        self._assert_external_inputs(fastq_dir, seq_xlsx, sample_tale_xlsx, tale_array_xlsx, golden_path)
        required_ids = {71, 72, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85}
        if not required_ids.issubset(set(discover_fastq_pairs(fastq_dir))):
            self.skipTest("Missing raw FASTQ pairs for the full 260304 regression scope")

        config = AnalysisConfig(
            fastq_dir=fastq_dir,
            seq_xlsx=seq_xlsx,
            sample_tale_xlsx=sample_tale_xlsx,
            tale_array_xlsx=tale_array_xlsx,
            sample_ids=(71, 72, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85),
            exclude_samples=(73, 74),
            target_seq="GCTCACGGTTATTTTGGCCGAT",
            editor_type="taled",
            date_tag="990304",
            output_base_dir=self.tmp_dir,
        )
        result = run_analysis(config)
        out_rows = read_tsv(result.key_output_paths["per_sample_editing"])
        golden_rows = read_tsv(golden_path)

        actual = {
            int(row["sample_id"]): row["edited_pct_allowed_only"]
            for row in out_rows
        }
        golden = {
            int(row["sample_id"]): row["edited_pct_or_allowed"]
            for row in golden_rows
        }
        self.assertEqual(actual, golden)


if __name__ == "__main__":
    unittest.main()
