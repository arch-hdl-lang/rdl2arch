"""Emit the top ARCH regblock module: bus decl + module with regs, seq, comb."""

from .cpuif.base import CpuifBase
from .emit_field_logic import (
    field_hwif_in_seq,
    field_hwif_out_comb,
    field_read_side_stmts,
    field_write_stmts,
    reg_read_expr,
)
from .scan_design import DesignModel


def _indent(text: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + ln if ln else ln for ln in text.splitlines())


def _reset_struct_literal(reg) -> str:
    inner = ", ".join(f"{f.name}: {f.reset}" for f in reg.fields)
    return f"{reg.struct_name} {{ {inner} }}"


def emit_regblock(design: DesignModel, cpuif: CpuifBase) -> str:
    lines: list[str] = []
    lines.append(f"use {design.package_name};")
    lines.append("")
    lines.append(cpuif.bus_declaration())
    lines.append("")
    lines.append(f"module {design.module_name}")
    lines.append("  port clk:      in Clock<SysDomain>;")
    lines.append("  port rst:      in Reset<Sync>;")
    lines.append(cpuif.subordinate_port())
    lines.append(f"  port hwif_in:  in {design.hwif_in_struct};")
    lines.append(f"  port hwif_out: out {design.hwif_out_struct};")
    lines.append("")
    lines.append("  default seq on clk rising;")
    lines.append("")

    # --- Register state declarations ----------------------------------------
    for reg in design.regs:
        lines.append(f"  reg {reg.state_name}: {reg.struct_name} "
                     f"reset rst => {_reset_struct_literal(reg)};")
    lines.append("")

    # --- CPU-interface handshake --------------------------------------------
    # Re-indent cpuif fragment (dedent'd in cpuif impl) to module-body level.
    lines.append(_indent(cpuif.handshake_state(), 2))
    lines.append("")

    # --- Combinational readback mux (module-scope let) ----------------------
    # Always emitted. Registered cpuifs latch into rdata_r; combinational
    # cpuifs drive their read-data output from this directly.
    rd_addr = cpuif.rd_addr_expr()
    lines.append(f"  let rdata_mux: UInt<{design.data_width}> = match {rd_addr}")
    for reg in design.regs:
        expr = reg_read_expr(reg, design.data_width)
        lines.append(
            f"    {design.addr_width}'h{reg.address:x} => {expr},"
        )
    lines.append("    _ => 0")
    lines.append("  end match;")
    lines.append("")

    # --- Sequential write / read-side-effects / hwif_in copy ----------------
    lines.append("  seq")

    # Handshake latches
    lines.append(_indent(cpuif.handshake_seq(), 4))

    # hwif_in -> reg state (continuous)
    for reg in design.regs:
        for f in reg.fields:
            for stmt in field_hwif_in_seq(f, reg):
                lines.append(f"    {stmt}")

    # sw writes: if wr_fire, match address, per-reg write block
    wr_fire = cpuif.wr_fire_expr()
    wr_addr = cpuif.wr_addr_expr()
    wdata = cpuif.wdata_expr()

    per_reg_writes: list[tuple] = []
    for reg in design.regs:
        write_stmts: list[str] = []
        for f in reg.fields:
            write_stmts += field_write_stmts(f, reg, wdata)
        if write_stmts:
            per_reg_writes.append((reg, write_stmts))
    if per_reg_writes:
        lines.append(f"    if {wr_fire}")
        for reg, write_stmts in per_reg_writes:
            lines.append(
                f"      if {wr_addr} == {design.addr_width}'h{reg.address:x}"
            )
            for stmt in write_stmts:
                lines.append(f"        {stmt}")
            lines.append(f"      end if")
        lines.append("    end if")

    # Read-side effects (rclr/rset) on read-fire
    rd_fire = cpuif.rd_fire_expr()
    any_read_effects = any(
        field_read_side_stmts(f, r) for r in design.regs for f in r.fields
    )
    if any_read_effects:
        lines.append(f"    if {rd_fire}")
        for reg in design.regs:
            stmts = [s for f in reg.fields for s in field_read_side_stmts(f, reg)]
            if not stmts:
                continue
            lines.append(
                f"      if {rd_addr} == {design.addr_width}'h{reg.address:x}"
            )
            for stmt in stmts:
                lines.append(f"        {stmt}")
            lines.append(f"      end if")
        lines.append("    end if")

    # Registered readback (AXI-style): latch the combinational rdata_mux into
    # rdata_r on read-fire. APB skips this path — its handshake_comb drives
    # prdata from rdata_mux directly.
    if not cpuif.combinational_readback:
        lines.append(f"    if {rd_fire}")
        lines.append(f"      rdata_r <= rdata_mux;")
        lines.append(f"    end if")

    lines.append("  end seq")
    lines.append("")

    # Combinational readback mux — always emitted as a module-scope let so both
    # registered and combinational cpuif styles can consume it.

    # --- Combinational handshake + hwif_out ---------------------------------
    lines.append("  comb")
    lines.append(_indent(cpuif.handshake_comb(), 4))
    lines.append("")
    any_hwif_out = False
    for reg in design.regs:
        for f in reg.fields:
            for stmt in field_hwif_out_comb(f, reg):
                lines.append(f"    {stmt}")
                any_hwif_out = True
    if not any_hwif_out:
        # Struct has a placeholder `_reserved` member; drive it to satisfy the
        # all-outputs-driven check.
        lines.append("    hwif_out._reserved = 0;")
    lines.append("  end comb")
    lines.append("")
    lines.append(f"end module {design.module_name}")
    lines.append("")
    return "\n".join(lines)
