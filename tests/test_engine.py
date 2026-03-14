from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from maund_local_app.engine import run_analysis, validate_config
from maund_local_app.io_utils import parse_id_spec, read_tsv
from maund_local_app.models import AnalysisConfig
from maund_workflow.run_pipeline import discover_fastq_pairs


DOWNLOADS = Path(os.environ.get("MAUND_TEST_INPUT_DIR", str(Path.home() / "Downloads")))


class ParseHelpersTest(unittest.TestCase):
    def test_parse_id_spec_supports_ranges(self) -> None:
        self.assertEqual(parse_id_spec("71,72,75-77,80~81"), (71, 72, 75, 76, 77, 80, 81))


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
