from __future__ import annotations

import pytest

pytest.importorskip("unidiff")

from missing_patch_detector.patch_collector import PatchCollector


SAMPLE_PATCH = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,2 +1,4 @@
 def parse_size(size):
+    if size < 0:
+        raise ValueError(\"invalid size\")
     return int(size)
"""


def test_parse_diff_extracts_added_removed_context() -> None:
    collector = PatchCollector()
    result = collector.parse_diff(SAMPLE_PATCH)

    assert len(result) == 1
    assert result[0].file_path == "app.py"
    assert "    if size < 0:" in result[0].added_lines
    assert "def parse_size(size):" in result[0].context_lines


def test_generate_llm_signature_uses_callback() -> None:
    collector = PatchCollector()
    parsed = collector.parse_diff(SAMPLE_PATCH)

    seen: dict[str, str] = {}

    def fake_summary(prompt: str) -> str:
        seen["prompt"] = prompt
        return "Adds negative size guard"

    signature = collector.generate_llm_signature(parsed, summarizer=fake_summary)
    assert signature == "Adds negative size guard"
    assert "app.py" in seen["prompt"]
