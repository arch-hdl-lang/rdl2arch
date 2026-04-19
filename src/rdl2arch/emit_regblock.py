"""Emit the top ARCH regblock module: bus decl + module with regs, seq, comb."""

from .cpuif.base import CpuifBase
from .emit_field_logic import (
    field_hwif_in_seq,
    field_hwif_out_comb,
    field_read_side_stmts,
    field_write_stmts,
    reg_read_expr,
)
from .scan_design import DesignModel, RegModel


def _indent(text: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + ln if ln else ln for ln in text.splitlines())


def _reset_struct_literal(reg: RegModel) -> str:
    inner = ", ".join(f"{f.name}: {f.reset}" for f in reg.fields)
    return f"{reg.struct_name} {{ {inner} }}"


def _addr_literal(addr_width: int, value: int) -> str:
    return f"{addr_width}'h{value:x}"


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
    # Scalars: one struct-typed reg. Arrays: one Vec-typed reg whose reset
    # value is a single struct literal applied to every element.
    for reg in design.regs:
        if reg.is_array:
            lines.append(
                f"  reg {reg.state_name}: Vec<{reg.struct_name}, {reg.array_count}> "
                f"reset rst => {_reset_struct_literal(reg)};"
            )
        else:
            lines.append(
                f"  reg {reg.state_name}: {reg.struct_name} "
                f"reset rst => {_reset_struct_literal(reg)};"
            )
    lines.append("")

    # --- CPU-interface handshake --------------------------------------------
    lines.append(_indent(cpuif.handshake_state(), 2))
    lines.append("")

    # --- Combinational readback mux -----------------------------------------
    rd_addr = cpuif.rd_addr_expr()
    lines.append(f"  let rdata_mux: UInt<{design.data_width}> = match {rd_addr}")
    for reg in design.regs:
        for elem_idx, addr in reg.elements():
            expr = reg_read_expr(reg, reg.state_ref(elem_idx), design.data_width)
            lines.append(f"    {_addr_literal(design.addr_width, addr)} => {expr},")
    lines.append("    _ => 0")
    lines.append("  end match;")
    lines.append("")

    # --- Sequential write / read-side-effects / hwif_in copy ----------------
    wr_fire = cpuif.wr_fire_expr()
    wr_addr = cpuif.wr_addr_expr()
    wdata = cpuif.wdata_expr()
    rd_fire = cpuif.rd_fire_expr()

    lines.append("  seq")
    lines.append(_indent(cpuif.handshake_seq(), 4))

    # hwif_in -> reg state (continuous). Iterated per-element in Python here
    # rather than inside generate_for, because hwif member names embed the
    # element index (`<reg>_<i>_<field>`) — that form has `_i_` mid-name
    # which the elaborator's subst_expr_names suffix-rewriter doesn't touch.
    # Driving from module scope sidesteps the issue.
    for reg in design.regs:
        for elem_idx, _ in reg.elements():
            for f in reg.fields:
                for stmt in field_hwif_in_seq(
                    f, reg.state_ref(elem_idx), reg.hwif_member(elem_idx, f.name)
                ):
                    lines.append(f"    {stmt}")

    # sw writes to scalar regs — one address-decoded if-block per reg.
    scalar_writes: list[tuple] = []
    for reg in design.regs:
        if reg.is_array:
            continue
        stmts: list[str] = []
        for f in reg.fields:
            stmts += field_write_stmts(f, reg.state_ref(0), wdata)
        if stmts:
            scalar_writes.append((reg, stmts))
    if scalar_writes:
        lines.append(f"    if {wr_fire}")
        for reg, stmts in scalar_writes:
            lines.append(
                f"      if {wr_addr} == {_addr_literal(design.addr_width, reg.base_address)}"
            )
            for stmt in stmts:
                lines.append(f"        {stmt}")
            lines.append(f"      end if")
        lines.append("    end if")

    # Read-side effects (rclr/rset) for scalar regs.
    scalar_reads: list[tuple] = []
    for reg in design.regs:
        if reg.is_array:
            continue
        stmts = [s for f in reg.fields for s in field_read_side_stmts(f, reg.state_ref(0))]
        if stmts:
            scalar_reads.append((reg, stmts))
    if scalar_reads:
        lines.append(f"    if {rd_fire}")
        for reg, stmts in scalar_reads:
            lines.append(
                f"      if {cpuif.rd_addr_expr()} == "
                f"{_addr_literal(design.addr_width, reg.base_address)}"
            )
            for stmt in stmts:
                lines.append(f"        {stmt}")
            lines.append("      end if")
        lines.append("    end if")

    # Registered readback latch (AXI-style): rdata_r <= rdata_mux on rd_fire.
    if not cpuif.combinational_readback:
        lines.append(f"    if {rd_fire}")
        lines.append(f"      rdata_r <= rdata_mux;")
        lines.append("    end if")

    lines.append("  end seq")
    lines.append("")

    # --- Per-array generate_for write blocks --------------------------------
    # One generate_for per array reg: each iteration drives `state[i].field`
    # if the bus address matches `base + i * stride`. Reading B's write-target
    # check passes since every LHS is `<state>[i].<field>` indexed by the
    # loop var. Hwif drives for arrays go in separate per-element comb/seq
    # below since hwif member names embed the element index (which can't be
    # expressed inside a generate_for body).
    for reg in design.regs:
        if not reg.is_array:
            continue
        # Generate one write block (covers sw writes + hwif_in continuous drives
        # + read-side effects) using generate_for indexed by `i`.
        n = reg.array_count
        stride = reg.array_stride
        base = reg.base_address
        loop_state = f"{reg.state_name}[i]"

        write_stmts = [s for f in reg.fields
                       for s in field_write_stmts(f, loop_state, wdata)]
        rclr_stmts  = [s for f in reg.fields
                       for s in field_read_side_stmts(f, loop_state)]

        if not (write_stmts or rclr_stmts):
            continue

        lines.append(f"  generate_for i in 0..{n - 1}")
        lines.append("    seq")
        if write_stmts:
            lines.append(f"      if {wr_fire} and {wr_addr} == "
                         f"{_addr_literal(design.addr_width, base)} + i * {stride}")
            for stmt in write_stmts:
                lines.append(f"        {stmt}")
            lines.append("      end if")
        if rclr_stmts:
            lines.append(f"      if {rd_fire} and {cpuif.rd_addr_expr()} == "
                         f"{_addr_literal(design.addr_width, base)} + i * {stride}")
            for stmt in rclr_stmts:
                lines.append(f"        {stmt}")
            lines.append("      end if")
        lines.append("    end seq")
        lines.append("  end generate_for")
        lines.append("")

    # --- Combinational handshake + hwif_out ---------------------------------
    lines.append("  comb")
    lines.append(_indent(cpuif.handshake_comb(), 4))
    lines.append("")
    any_hwif_out = False
    for reg in design.regs:
        for elem_idx, _ in reg.elements():
            for f in reg.fields:
                if not f.hw_readable:
                    continue
                lines.append(
                    f"    hwif_out.{reg.hwif_member(elem_idx, f.name)} = "
                    f"{reg.state_ref(elem_idx)}.{f.name};"
                )
                any_hwif_out = True
    if not any_hwif_out:
        lines.append("    hwif_out._reserved = 0;")
    lines.append("  end comb")
    lines.append("")
    lines.append(f"end module {design.module_name}")
    lines.append("")
    return "\n".join(lines)
