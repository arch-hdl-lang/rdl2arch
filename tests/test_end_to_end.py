"""End-to-end: RDL fixture -> rdl2arch -> arch build must succeed cleanly."""

from pathlib import Path

import pytest
from systemrdl import RDLCompiler

from rdl2arch import ArchExporter
from rdl2arch.cpuif import APB4_Cpuif, AXI4Lite_Cpuif

from conftest import rdl_fixtures, run_arch


CPUIFS = {
    "axi4-lite": AXI4Lite_Cpuif,
    "apb4": APB4_Cpuif,
}


@pytest.mark.parametrize("cpuif_name", CPUIFS.keys())
@pytest.mark.parametrize("rdl_file", rdl_fixtures(), ids=lambda p: p.stem)
def test_arch_build(rdl_file: Path, cpuif_name: str, arch_bin: str,
                    tmp_path: Path) -> None:
    rdlc = RDLCompiler()
    rdlc.compile_file(str(rdl_file))
    root = rdlc.elaborate()

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    files = ArchExporter().export(
        root.top, str(out_dir), cpuif_cls=CPUIFS[cpuif_name]
    )
    assert files, "exporter produced no files"

    arch_inputs = sorted(out_dir.glob("*.arch"))

    check = run_arch(arch_bin, "check", arch_inputs, out_dir)
    assert check.returncode == 0, (
        f"arch check failed:\nSTDERR:\n{check.stderr}\nSTDOUT:\n{check.stdout}"
    )

    build = run_arch(arch_bin, "build", arch_inputs, out_dir)
    assert build.returncode == 0, (
        f"arch build failed:\nSTDERR:\n{build.stderr}\nSTDOUT:\n{build.stdout}"
    )

    svs = sorted(out_dir.glob("*.sv"))
    assert svs, "arch build did not emit any .sv output"
