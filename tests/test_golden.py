"""Golden-output diff tests.

For every (RDL fixture, cpuif) pair, regenerate ARCH source and diff against
checked-in expected output under `tests/expected/<fixture>-<cpuif>/`. Catches
unintended emitter changes — including ones that still pass `arch build` but
alter the emitted code in surprising ways.

To refresh the golden files after an intentional emitter change, run:
    UPDATE_GOLDEN=1 pytest tests/test_golden.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from systemrdl import RDLCompiler

from rdl2arch import ArchExporter
from rdl2arch.cpuif import APB4_Cpuif, AXI4Lite_Cpuif

from conftest import RDL_DIR


EXPECTED_DIR = Path(__file__).parent / "expected"
CPUIFS = {"axi4-lite": AXI4Lite_Cpuif, "apb4": APB4_Cpuif}
FIXTURES = ["minimal", "access_types", "arrays_and_regfile", "readonly", "interrupts"]


def _update_mode() -> bool:
    return os.environ.get("UPDATE_GOLDEN") == "1"


@pytest.mark.parametrize("cpuif_name", CPUIFS.keys())
@pytest.mark.parametrize("fixture", FIXTURES)
def test_golden(fixture: str, cpuif_name: str, tmp_path: Path) -> None:
    rdlc = RDLCompiler()
    rdlc.compile_file(str(RDL_DIR / f"{fixture}.rdl"))
    root = rdlc.elaborate()
    ArchExporter().export(root.top, str(tmp_path), cpuif_cls=CPUIFS[cpuif_name])

    generated = {p.name: p.read_text() for p in sorted(tmp_path.glob("*.arch"))}
    expected_dir = EXPECTED_DIR / f"{fixture}-{cpuif_name}"

    if _update_mode():
        expected_dir.mkdir(parents=True, exist_ok=True)
        # Purge stale files so removed outputs don't linger in the golden set.
        for stale in expected_dir.glob("*.arch"):
            if stale.name not in generated:
                stale.unlink()
        for name, content in generated.items():
            (expected_dir / name).write_text(content)
        return

    assert expected_dir.is_dir(), (
        f"Missing golden directory {expected_dir}. "
        f"Run: UPDATE_GOLDEN=1 pytest tests/test_golden.py"
    )
    expected = {p.name: p.read_text() for p in sorted(expected_dir.glob("*.arch"))}
    missing = set(expected) - set(generated)
    extra = set(generated) - set(expected)
    assert not missing, f"Generator no longer produces: {sorted(missing)}"
    assert not extra, f"Generator produced unexpected files: {sorted(extra)}"
    for name, gen_text in generated.items():
        assert gen_text == expected[name], (
            f"Mismatch in {fixture}-{cpuif_name}/{name}. "
            f"Run UPDATE_GOLDEN=1 pytest tests/test_golden.py to refresh if "
            f"the change was intentional."
        )
