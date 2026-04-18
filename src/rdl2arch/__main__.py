"""rdl2arch command-line entry point."""

import argparse
import sys

from systemrdl import RDLCompileError, RDLCompiler

from .cpuif.apb4 import APB4_Cpuif
from .cpuif.axi4lite import AXI4Lite_Cpuif
from .exporter import ArchExporter


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="rdl2arch",
        description="Generate ARCH register-block source from SystemRDL input.",
    )
    p.add_argument("input", help="SystemRDL input file (.rdl)")
    p.add_argument("-o", "--output-dir", default=".", help="Output directory")
    p.add_argument("--cpuif", choices=["axi4-lite", "apb4"], default="axi4-lite",
                   help="CPU interface protocol")
    p.add_argument("--module-name", help="Override module name (default: from RDL top)")
    p.add_argument("--package-name", help="Override package name")
    p.add_argument("--data-width", type=int, default=32, help="Bus data width")
    args = p.parse_args(argv)

    rdlc = RDLCompiler()
    try:
        rdlc.compile_file(args.input)
        root = rdlc.elaborate()
    except RDLCompileError:
        return 1

    cpuif_cls = {
        "axi4-lite": AXI4Lite_Cpuif,
        "apb4": APB4_Cpuif,
    }[args.cpuif]

    files = ArchExporter().export(
        root.top,
        args.output_dir,
        cpuif_cls=cpuif_cls,
        module_name=args.module_name,
        package_name=args.package_name,
        data_width=args.data_width,
    )
    for _, path in files.items():
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
