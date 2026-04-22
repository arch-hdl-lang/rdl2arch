"""Top-level exporter: orchestrates scan, validate, emit for an RDL root."""

import os
from typing import Optional, Type, Union

from systemrdl.node import AddrmapNode, RootNode

from .cpuif.axi4lite import AXI4Lite_Cpuif
from .cpuif.base import CpuifBase
from .emit_package import emit_package
from .emit_regblock import ResetStyle, emit_regblock
from .scan_design import scan
from .validate_design import validate


class ArchExporter:
    def export(
        self,
        node: Union[RootNode, AddrmapNode],
        output_dir: str,
        *,
        cpuif_cls: Type[CpuifBase] = AXI4Lite_Cpuif,
        module_name: Optional[str] = None,
        package_name: Optional[str] = None,
        data_width: int = 32,
        reset_style: ResetStyle = ResetStyle.SYNC,
        addr_width: Optional[int] = None,
        port_name: Optional[str] = None,
        combinational_readback: Optional[bool] = None,
    ) -> dict[str, str]:
        """Emit ARCH source files to output_dir. Returns {filename: path}.

        Optional overrides (all default to None / library default):
          - `reset_style`: emitted `rst` port type. `SYNC` is the
            historical default; use `ASYNC_LOW` for RISC-V/Ibex-style
            integrations where the core clock is gated during reset.
          - `addr_width`: override the auto-derived address width
            (default: `max_addr.bit_length()`).
          - `port_name`: override the cpuif's subordinate port name
            (default: cpuif class attr, e.g. `s_axi` / `s_apb`).
          - `combinational_readback`: override the cpuif's readback
            timing (default: cpuif class attr, e.g. AXI=False / APB=True).
        """
        if isinstance(node, RootNode):
            top = node.top
        else:
            top = node

        design = scan(
            top,
            module_name=module_name,
            package_name=package_name,
            data_width=data_width,
            addr_width=addr_width,
        )
        validate(design)

        cpuif = cpuif_cls(
            addr_width=design.addr_width,
            data_width=design.data_width,
            port_name=port_name,
            combinational_readback=combinational_readback,
        )

        pkg_src = emit_package(design)
        mod_src = emit_regblock(design, cpuif, reset_style=reset_style)

        os.makedirs(output_dir, exist_ok=True)
        pkg_path = os.path.join(output_dir, f"{design.package_name}.arch")
        mod_path = os.path.join(output_dir, f"{design.module_name}.arch")
        with open(pkg_path, "w") as fh:
            fh.write(pkg_src)
        with open(mod_path, "w") as fh:
            fh.write(mod_src)

        return {
            f"{design.package_name}.arch": pkg_path,
            f"{design.module_name}.arch": mod_path,
        }
