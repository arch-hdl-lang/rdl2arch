"""End-to-end verification against the emitted SystemVerilog via Verilator + cocotb.

For each (RDL fixture, cpuif) combo:
  1. Generate ARCH via rdl2arch.
  2. Compile ARCH to SV via `arch build`.
  3. Verilate the SV and run a cocotb test module against it.
The cocotb tests mirror the functional tests that run against `arch sim`; green
on both paths means the SV and C++ translations agree with the RDL spec.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from systemrdl import RDLCompiler

from rdl2arch import ArchExporter
from rdl2arch.cpuif import APB4_Cpuif, AXI4Lite_Cpuif

from conftest import RDL_DIR


COCOTB_TESTS_DIR = Path(__file__).parent / "cocotb_sv" / "cocotb_tests"

# Per-fixture config: which cocotb test module, and which cpuifs to exercise.
FIXTURES = {
    "minimal":              "test_minimal",
    "access_types":         "test_access_types",
    "arrays_and_regfile":   "test_arrays_and_regfile",
    "readonly":             "test_readonly",
    "interrupts":           "test_interrupts",
}

CPUIFS = {
    "axi4-lite": AXI4Lite_Cpuif,
    "apb4":      APB4_Cpuif,
}

pytest.importorskip("cocotb_tools.runner")
if shutil.which("verilator") is None:
    pytest.skip("Verilator not found on PATH", allow_module_level=True)


def _arch_build(arch_bin: str, out_dir: Path) -> list[Path]:
    arch_inputs = sorted(out_dir.glob("*.arch"))
    result = subprocess.run(
        [arch_bin, "build", *[str(p) for p in arch_inputs]],
        cwd=out_dir, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"arch build failed:\n{result.stderr}\n{result.stdout}"
        )
    return sorted(out_dir.glob("*.sv"))


def _generate(rdl_file: Path, cpuif_cls, out_dir: Path, *, name_suffix: str
              ) -> tuple[str, list[Path]]:
    rdlc = RDLCompiler()
    rdlc.compile_file(str(rdl_file))
    root = rdlc.elaborate()
    top_name = root.top.inst_name
    camel = "".join(p[:1].upper() + p[1:] for p in top_name.split("_") if p)
    module_name = camel + name_suffix
    package_name = module_name + "Pkg"
    ArchExporter().export(
        root.top, str(out_dir),
        cpuif_cls=cpuif_cls,
        module_name=module_name,
        package_name=package_name,
    )
    return module_name, [out_dir / f"{package_name}.arch",
                         out_dir / f"{module_name}.arch"]


@pytest.mark.parametrize("cpuif_name", CPUIFS.keys())
@pytest.mark.parametrize("fixture", FIXTURES.keys())
def test_verilator(fixture: str, cpuif_name: str, arch_bin: str,
                   tmp_path: Path) -> None:
    from cocotb_tools.runner import get_runner

    cpuif_cls = CPUIFS[cpuif_name]
    name_suffix = {"axi4-lite": "Axi", "apb4": "Apb"}[cpuif_name]
    rdl_file = RDL_DIR / f"{fixture}.rdl"

    out_dir = tmp_path / "gen"
    out_dir.mkdir()
    module_name, _ = _generate(rdl_file, cpuif_cls, out_dir,
                               name_suffix=name_suffix)

    # arch build -> SV
    sv_files = _arch_build(arch_bin, out_dir)
    assert sv_files, "arch build produced no .sv output"
    # Package .sv must come first for Verilator's compile order.
    sv_files.sort(key=lambda p: (0 if "Pkg" in p.name else 1, p.name))

    test_module = FIXTURES[fixture]

    runner = get_runner("verilator")
    build_dir = tmp_path / "sim_build"
    runner.build(
        verilog_sources=[str(p) for p in sv_files],
        hdl_toplevel=module_name,
        build_dir=str(build_dir),
        always=True,
        build_args=["--trace", "-Wno-IMPORTSTAR", "-Wno-WIDTHEXPAND"],
    )

    env = {"COCOTB_CPUIF": cpuif_name}
    # Keep the XML filename free of pytest-ID brackets; cocotb uses it as a path.
    safe_id = f"{fixture}_{cpuif_name.replace('-', '_')}"
    results_xml = runner.test(
        test_module=test_module,
        hdl_toplevel=module_name,
        build_dir=str(build_dir),
        test_dir=str(COCOTB_TESTS_DIR),
        extra_env=env,
        results_xml=str(tmp_path / f"results_{safe_id}.xml"),
    )
    # results_xml is a Path; cocotb_tools.runner raises already on fail, but
    # double-check the xml reports zero failures.
    import xml.etree.ElementTree as ET
    tree = ET.parse(results_xml)
    root = tree.getroot()
    failures = int(root.attrib.get("failures", "0")) + int(root.attrib.get("errors", "0"))
    assert failures == 0, f"cocotb reported {failures} failures; see {results_xml}"
