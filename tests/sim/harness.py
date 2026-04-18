"""Build-once, reuse-many harness for sim-level tests.

Generates ARCH for a fixture, invokes `arch sim --pybind` to compile the
pybind11 `.so`, then imports it. Returns a factory for fresh DUT instances.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Type

from systemrdl import RDLCompiler

from rdl2arch import ArchExporter
from rdl2arch.cpuif.base import CpuifBase

ARCH_COM_ROOT = Path.home() / "github" / "arch-com"
ARCH_PYTHON = ARCH_COM_ROOT / "python"
ARCH_SHIM = ARCH_PYTHON / "cocotb_shim"


def _add_pythonpath(path: Path) -> None:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def build_sim(rdl_path: Path, cpuif_cls: Type[CpuifBase], out_dir: Path,
              arch_bin: str, *, name_suffix: str = "") -> str:
    """Generate ARCH, build pybind .so, return the pybind module's .so path.

    `name_suffix` is appended to the generated module+package name so that
    multiple fixtures built from the same RDL (e.g. one per cpuif) produce
    distinct pybind init symbols and can coexist in a single Python process.
    """
    rdlc = RDLCompiler()
    rdlc.compile_file(str(rdl_path))
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

    arch_inputs = sorted(str(p) for p in out_dir.glob("*.arch"))
    build_dir = out_dir / "arch_sim_build"
    result = subprocess.run(
        [arch_bin, "sim", "--pybind", "-o", str(build_dir), *arch_inputs],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"arch sim --pybind failed:\nSTDERR:\n{result.stderr}\nSTDOUT:\n{result.stdout}"
        )

    so_files = list(build_dir.glob("V*_pybind.*.so"))
    if not so_files:
        raise RuntimeError(f"No pybind .so in {build_dir}")
    so = so_files[0]
    # Return the .so path — the caller imports via importlib.util so each build
    # gets a fresh module object. Plain `import` caches by module name and
    # would conflate two fixtures that share an RDL top name.
    #
    # Deliberately do NOT add cocotb_shim to sys.path here: it would pollute
    # PYTHONPATH for later subprocess-based tests (cocotb_tools.runner inherits
    # the env, and the shim masks real cocotb imports).
    return str(so)


def fresh_dut(so_path: str):
    so = Path(so_path)
    mod_name = so.name.split(".")[0]
    # Purge any previously-loaded module of the same name so we bind to the
    # .so at so_path rather than whatever was loaded for a sibling fixture.
    sys.modules.pop(mod_name, None)
    spec = importlib.util.spec_from_file_location(mod_name, so_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load pybind module from {so_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    cls_name = mod_name.replace("_pybind", "")
    cls = getattr(module, cls_name)
    return cls()
