"""Emit the shared ARCH package: CSR-address enum, per-register structs, hwif structs."""

from .scan_design import DesignModel


def emit_package(design: DesignModel) -> str:
    lines: list[str] = []
    lines.append(f"package {design.package_name}")
    lines.append("")

    # CSR address enum — one variant per address-decoded entry. Arrays expand
    # to N variants (Ch0, Ch1, ...); scalars produce a single variant.
    csr_variants: list[str] = []
    for reg in design.regs:
        for elem_idx, _ in reg.elements():
            csr_variants.append(reg.enum_variant_for(elem_idx))
    lines.append(f"  enum {design.csr_enum_name}")
    for i, name in enumerate(csr_variants):
        sep = "," if i < len(csr_variants) - 1 else ""
        lines.append(f"    {name}{sep}")
    lines.append(f"  end enum {design.csr_enum_name}")
    lines.append("")

    # One struct per register declaration (shared across array elements).
    for reg in design.regs:
        lines.append(f"  struct {reg.struct_name}")
        for f in reg.fields:
            lines.append(f"    {f.name}: UInt<{f.width}>;")
        lines.append(f"  end struct {reg.struct_name}")
        lines.append("")

    # Hwif in: hw-writable fields become per-element scalar inputs. Iterating
    # each (reg, elem, field) keeps the hwif interface flat — consumers can
    # wire individual bits without unpacking a Vec.
    lines.append(f"  struct {design.hwif_in_struct}")
    in_members = [
        (reg.hwif_member(elem_idx, f.name), f.width)
        for reg in design.regs
        for elem_idx, _ in reg.elements()
        for f in reg.fields
        if f.hw_writable
    ]
    if not in_members:
        lines.append("    _reserved: UInt<1>;")
    else:
        for name, w in in_members:
            lines.append(f"    {name}: UInt<{w}>;")
    lines.append(f"  end struct {design.hwif_in_struct}")
    lines.append("")

    # Hwif out: hw-readable fields become per-element scalar outputs.
    lines.append(f"  struct {design.hwif_out_struct}")
    out_members = [
        (reg.hwif_member(elem_idx, f.name), f.width)
        for reg in design.regs
        for elem_idx, _ in reg.elements()
        for f in reg.fields
        if f.hw_readable
    ]
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
