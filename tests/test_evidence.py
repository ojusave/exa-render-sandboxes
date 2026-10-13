"""Check that the published example and evidence describe the same file bytes."""

# These checks read fixed files only. They never run generated code or call a provider.
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PublishedEvidenceTests(unittest.TestCase):
    def test_live_source_and_saved_repairs_match_the_record(self):
        """Prevent publication from silently changing the code that was actually tested."""
        evidence = json.loads((ROOT / "evidence.json").read_text())
        for comparison in evidence["comparisons"]:
            fingerprints = dict(comparison["source_sha256"])
            for trial in comparison["trials"]:
                fingerprints[trial["candidate_file"]] = trial["source_sha256"]
            for name, expected in fingerprints.items():
                with self.subTest(file=name):
                    observed = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                    self.assertEqual(observed, expected)

    def test_summary_matches_each_recorded_verification_case(self):
        """A headline pass count must agree with the individual results readers can inspect."""
        evidence = json.loads((ROOT / "evidence.json").read_text())
        cases = json.loads((ROOT / "shared/cases.json").read_text())
        expected_names = [row["name"] for row in cases["public"] + cases["held_out"]]
        for comparison in evidence["comparisons"]:
            for trial in comparison["trials"]:
                with self.subTest(language=comparison["language"], mode=trial["mode"]):
                    results = trial["verification"]
                    self.assertEqual([row["name"] for row in results], expected_names)
                    self.assertEqual(sum(row["passed"] for row in results), trial["checks_passed"])
                    self.assertEqual(len(results), trial["checks_total"])
                    self.assertEqual(all(row["passed"] for row in results), trial["passed"])


if __name__ == "__main__":
    unittest.main()
