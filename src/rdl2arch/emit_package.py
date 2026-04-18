"""Emit the shared ARCH package: CSR-address enum, per-register structs, hwif structs."""

from .scan_design import DesignModel


def emit_package(design: DesignModel) -> str:
    lines: list[str] = []
    lines.append(f"package {design.package_name}")
    lines.append("")

    # CSR address enum — variant order matches register declaration order.
    lines.append(f"  enum {design.csr_enum_name}")
    for i, reg in enumerate(design.regs):
        sep = "," if i < len(design.regs) - 1 else ""
        lines.append(f"    {reg.enum_variant}{sep}")
    lines.append(f"  end enum {design.csr_enum_name}")
    lines.append("")

    # One struct per register.
    for reg in design.regs:
        lines.append(f"  struct {reg.struct_name}")
        for f in reg.fields:
            lines.append(f"    {f.name}: UInt<{f.width}>;")
        lines.append(f"  end struct {reg.struct_name}")
        lines.append("")

    # Hwif in: hw-writable fields (hw = w / rw) become inputs.
    lines.append(f"  struct {design.hwif_in_struct}")
    in_members = [(f.hwif_in_name, f.width) for r in design.regs for f in r.fields
                  if f.hw_writable]
    if not in_members:
        lines.append("    _reserved: UInt<1>;")
    else:
        for name, w in in_members:
            lines.append(f"    {name}: UInt<{w}>;")
    lines.append(f"  end struct {design.hwif_in_struct}")
    lines.append("")

    # Hwif out: hw-readable fields (hw = r / rw) become outputs.
    lines.append(f"  struct {design.hwif_out_struct}")
    out_members = [(f.hwif_out_name, f.width) for r in design.regs for f in r.fields
                   if f.hw_readable]
    if not out_members:
        lines.append("    _reserved: UInt<1>;")
    else:
        for name, w in out_members:
            lines.append(f"    {name}: UInt<{w}>;")
    lines.append(f"  end struct {design.hwif_out_struct}")
    lines.append("")

    lines.append(f"end package {design.package_name}")
    lines.append("")
    return "\n".join(lines)
