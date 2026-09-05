"""Optional real-GPU E2E for 青渡川 — skipped unless explicitly selected."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

NOVEL = Path(r"D:\Develop\aiVedioProducer\docs\novels\青渡川.txt")
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "e2e_qingduchuan_flow.py"
REPORT = Path(__file__).resolve().parents[1] / "scripts" / "qingduchuan_e2e_report.json"

pytestmark = [pytest.mark.gpu, pytest.mark.slow]


@pytest.mark.skipif(not NOVEL.is_file(), reason="novel missing")
@pytest.mark.skipif(
    os.environ.get("N2L_RUN_GPU_E2E") != "1",
    reason="set N2L_RUN_GPU_E2E=1 to run real Comfy GPU E2E",
)
def test_qingduchuan_real_gpu_flow():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    base = os.environ.get("N2L_E2E_BASE_URL", "http://127.0.0.1:8790")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--base-url", base],
        cwd=str(SCRIPT.parent.parent),
        check=False,
    )
    assert proc.returncode == 0, f"e2e script failed rc={proc.returncode}"
    assert REPORT.is_file(), "report JSON missing"
    import json

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    assert payload.get("ok") is True
    assert payload.get("fake_comfy") is False
