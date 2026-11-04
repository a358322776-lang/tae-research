"""最终测试集格式测试（B1）。全部合成字典，不读、不写任何
真实数据文件，不创建测试数据。"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from testset_formats import (FormatError, manifest_template, spec_template,
                             summary_template, validate_manifest,
                             validate_spec, validate_summary, hash_dict)

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "test-sets" / "final-v1"


class TemplateTest(unittest.TestCase):
    def test_spec_template_validates(self):
        validate_spec(spec_template(), is_template=True)

    def test_spec_template_claims_not_frozen(self):
        spec = spec_template()
        self.assertEqual(spec["status"], "TEMPLATE-NOT-FROZEN")
        self.assertIsNone(spec["freeze_timestamp_ms"])
        self.assertIsNone(spec["windows"]["final_test"]["start_ms"])

    def test_spec_rejects_frozen_claim(self):
        spec = spec_template()
        spec["status"] = "FROZEN"
        with self.assertRaises(FormatError):
            validate_spec(spec, is_template=True)
        spec = spec_template()
        spec["freeze_timestamp_ms"] = 123
        with self.assertRaises(FormatError):
            validate_spec(spec, is_template=True)

    def test_spec_rejects_real_window_dates(self):
        spec = spec_template()
        spec["windows"]["final_test"]["start_ms"] = 1700000000000
        with self.assertRaises(FormatError):
            validate_spec(spec, is_template=True)

    def test_spec_rejects_missing_field(self):
        spec = spec_template()
        del spec["universe"]
        with self.assertRaises(FormatError):
            validate_spec(spec, is_template=True)

    def test_non_template_rejected_as_b3(self):
        with self.assertRaises(FormatError):
            validate_spec(spec_template(), is_template=False)


class ManifestTest(unittest.TestCase):
    def test_empty_manifest_validates(self):
        validate_manifest(manifest_template("0" * 64))

    def test_manifest_rejects_bad_hash(self):
        m = manifest_template("not-a-hash")
        with self.assertRaises(FormatError):
            validate_manifest(m)

    def test_manifest_rejects_duplicate_path(self):
        m = manifest_template("a" * 64)
        m["files"] = [
            {"path": "data/x.parquet", "sha256": "b" * 64, "rows": 10},
            {"path": "data/x.parquet", "sha256": "c" * 64, "rows": 10},
        ]
        with self.assertRaises(FormatError):
            validate_manifest(m)

    def test_manifest_rejects_bad_entry(self):
        m = manifest_template("a" * 64)
        m["files"] = [{"path": "data/x.parquet", "sha256": "b" * 64}]
        with self.assertRaises(FormatError):
            validate_manifest(m)

    def test_spec_hash_binds_manifest(self):
        # manifest 记载的 spec 哈希必须与规格字典的哈希一致。
        spec = spec_template()
        m = manifest_template(hash_dict(spec))
        validate_manifest(m)
        self.assertEqual(m["spec_sha256"], hash_dict(spec))
        m2 = manifest_template(hash_dict({**spec, "universe": ["BTC"]}))
        self.assertNotEqual(m["spec_sha256"], m2["spec_sha256"])


class SummaryTest(unittest.TestCase):
    def test_summary_template_validates(self):
        validate_summary(summary_template())

    def test_summary_rejects_raw_data(self):
        s = summary_template()
        s["bars"] = [1, 2, 3]
        with self.assertRaises(FormatError):
            validate_summary(s)

    def test_summary_rejects_inverted_range(self):
        s = summary_template()
        s["bar_count_range"] = [100, 10]
        with self.assertRaises(FormatError):
            validate_summary(s)


class OnDiskTemplatesTest(unittest.TestCase):
    def test_files_exist_and_match_generators(self):
        spec_md = (TEMPLATES / "spec-template.md").read_text(
            encoding="utf-8")
        self.assertIn("TEMPLATE-NOT-FROZEN", spec_md)
        self.assertIn("未冻结", spec_md)
        manifest = json.loads(
            (TEMPLATES / "manifest-template.json").read_text(
                encoding="utf-8"))
        validate_manifest(manifest)
        self.assertEqual(manifest["files"], [])
        summary = json.loads(
            (TEMPLATES / "summary-template.json").read_text(
                encoding="utf-8"))
        validate_summary(summary)
        self.assertEqual(summary["bar_count_range"], [None, None])

    def test_data_dir_empty(self):
        data_dir = TEMPLATES / "data"
        real = [p for p in data_dir.iterdir() if p.name != ".gitkeep"]
        self.assertEqual(real, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
