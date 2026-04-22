"""Per-field ARCH code fragments: write-side seq, hwif-in seq, hwif-out comb,
and readback expressions.

The functions take a `state_ref` string for the element being acted on, which
is `<reg>_r` for scalar regs or `<reg>_r[<idx>]` for array elements. Callers
in emit_regblock supply the right form per element.
"""

from systemrdl.rdltypes import OnReadType, OnWriteType

from .scan_design import FieldModel, RegModel


def _wdata_slice(wdata_expr: str, field: FieldModel) -> str:
    if field.width == 1:
        return f"{wdata_expr}[{field.lsb}]"
    return f"{wdata_expr}[{field.msb}:{field.lsb}]"


def _ones_literal(width: int) -> str:
    if width == 1:
        return "true"
    mask = (1 << width) - 1
    return f"{width}'h{mask:x}"


def _zero_literal(width: int) -> str:
    if width == 1:
        return "false"
    return f"{width}'h0"


def field_write_stmts(field: FieldModel, state_ref: str, wdata_expr: str) -> list[str]:
    """ARCH seq statements for a CPU write to this field. Caller wraps in the
    address-decoded `if`. `state_ref` is the per-element storage reference."""
    if not field.sw_writable:
        return []
    lhs = f"{state_ref}.{field.name}"
    slice_expr = _wdata_slice(wdata_expr, field)
    ones = _ones_literal(field.width)
    zeros = _zero_literal(field.width)

    ow = field.onwrite
    if ow is None:
        return [f"{lhs} <= {slice_expr};"]
    if ow == OnWriteType.woclr:
        return [f"{lhs} <= {lhs} & (~{slice_expr});"]
    if ow == OnWriteType.woset:
        return [f"{lhs} <= {lhs} | {slice_expr};"]
    if ow == OnWriteType.wclr:
        return [f"{lhs} <= {zeros};"]
    if ow == OnWriteType.wset:
        return [f"{lhs} <= {ones};"]
    if ow == OnWriteType.wot:
        return [f"{lhs} <= {lhs} ^ {slice_expr};"]
    if ow == OnWriteType.wzc:
        return [f"{lhs} <= {lhs} & {slice_expr};"]
    if ow == OnWriteType.wzs:
        return [f"{lhs} <= {lhs} | (~{slice_expr});"]
    if ow == OnWriteType.wzt:
        return [f"{lhs} <= {lhs} ^ (~{slice_expr});"]
    raise NotImplementedError(f"onwrite={ow}")


def field_read_side_stmts(field: FieldModel, state_ref: str) -> list[str]:
    """rclr / rset statements that fire on a CPU read."""
    if field.onread is None:
        return []
    lhs = f"{state_ref}.{field.name}"
    if field.onread == OnReadType.rclr:
        return [f"{lhs} <= {_zero_literal(field.width)};"]
    if field.onread == OnReadType.rset:
        return [f"{lhs} <= {_ones_literal(field.width)};"]
    raise NotImplementedError(f"onread={field.onread}")


def field_hwif_in_seq(field: FieldModel, state_ref: str, hwif_member: str) -> list[str]:
    """Continuous register copy from hwif_in to the field state (when hw drives).

    For sticky interrupt fields (`intr` + `stickybit`) we emit an
    OR-latch instead of a plain copy so any 1 cycle of hwif_in high
    stays latched high until SW write-1-to-clear resets it. This
    runs on every clock edge — the downstream `if wr_fire` SW-write
    branch overrides in the same cycle via last-write-wins seq
    semantics (SW w1c beats HW-set on conflict; next cycle the
    OR-latch re-asserts if HW is still driving high, which is the
    standard sticky precedence).
    """
    if not field.hw_writable:
        return []
    lhs = f"{state_ref}.{field.name}"
    rhs = f"hwif_in.{hwif_member}"
    if field.is_intr and field.is_stickybit:
        return [f"{lhs} <= {lhs} | {rhs};"]
    return [f"{lhs} <= {rhs};"]


def field_hwif_out_comb(field: FieldModel, state_ref: str, hwif_member: str) -> list[str]:
    """Combinational drive of hwif_out from field state."""
    if not field.hw_readable:
        return []
    return [f"hwif_out.{hwif_member} = {state_ref}.{field.name};"]


def reg_read_expr(reg: RegModel, state_ref: str, data_width: int) -> str:
    """Compose the readback value for one register (one element of an array, or
    the whole reg for a scalar). Pads to data_width with zeros."""
    if not reg.fields:
        return _zero_literal(data_width)

    # MSB-first concat: walk fields by descending lsb, padding holes with zeros.
    fields_sorted = sorted(reg.fields, key=lambda f: f.lsb, reverse=True)
    parts: list[str] = []
    next_bit = reg.regwidth - 1
    for f in fields_sorted:
        if f.msb < next_bit:
            gap = next_bit - f.msb
            parts.append(f"{gap}'h0")
        if f.sw_readable:
            parts.append(f"{state_ref}.{f.name}")
        else:
            parts.append(_zero_literal(f.width))
        next_bit = f.lsb - 1
    if next_bit >= 0:
        parts.append(f"{next_bit + 1}'h0")

    if reg.regwidth == data_width:
        if len(parts) == 1:
            return parts[0]
        return "{" + ", ".join(parts) + "}"
    pad = data_width - reg.regwidth
    body = parts[0] if len(parts) == 1 else "{" + ", ".join(parts) + "}"
    return "{" + f"{pad}'h0, {body}" + "}"
