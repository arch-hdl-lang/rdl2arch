"""Per-field ARCH code fragments: write-side seq, hwif-in seq, hwif-out comb,
and readback expressions."""

from systemrdl.rdltypes import OnReadType, OnWriteType

from .scan_design import FieldModel, RegModel


def _wdata_slice(wdata_expr: str, field: FieldModel) -> str:
    """Slice wdata for a field."""
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


def field_write_stmts(field: FieldModel, reg: RegModel, wdata_expr: str) -> list[str]:
    """Return the ARCH seq statements that fire on a CPU write to this field's
    parent register. Does NOT include the surrounding `if wr_fire and addr==...`
    — that's wrapped by the register-level emitter.
    """
    if not field.sw_writable:
        return []
    lhs = f"{reg.state_name}.{field.name}"
    slice_expr = _wdata_slice(wdata_expr, field)
    ones = _ones_literal(field.width)
    zeros = _zero_literal(field.width)

    ow = field.onwrite
    if ow is None:
        return [f"{lhs} <= {slice_expr};"]
    if ow == OnWriteType.woclr:
        # Write-one-to-clear: bits written as 1 are cleared.
        return [f"{lhs} <= {lhs} & (~{slice_expr});"]
    if ow == OnWriteType.woset:
        # Write-one-to-set: bits written as 1 are set.
        return [f"{lhs} <= {lhs} | {slice_expr};"]
    if ow == OnWriteType.wclr:
        # Any write clears the field.
        return [f"{lhs} <= {zeros};"]
    if ow == OnWriteType.wset:
        # Any write sets the field.
        return [f"{lhs} <= {ones};"]
    if ow == OnWriteType.wot:
        # Write-one-to-toggle
        return [f"{lhs} <= {lhs} ^ {slice_expr};"]
    if ow == OnWriteType.wzc:
        # Write-zero-to-clear: clear bits where wdata is 0 -> AND with wdata
        return [f"{lhs} <= {lhs} & {slice_expr};"]
    if ow == OnWriteType.wzs:
        # Write-zero-to-set: set bits where wdata is 0 -> OR with ~wdata
        return [f"{lhs} <= {lhs} | (~{slice_expr});"]
    if ow == OnWriteType.wzt:
        # Write-zero-to-toggle: toggle bits where wdata is 0 -> XOR with ~wdata
        return [f"{lhs} <= {lhs} ^ (~{slice_expr});"]
    raise NotImplementedError(f"onwrite={ow}")


def field_read_side_stmts(field: FieldModel, reg: RegModel) -> list[str]:
    """Statements for rclr / rset — fire on a CPU read to the parent register."""
    if field.onread is None:
        return []
    lhs = f"{reg.state_name}.{field.name}"
    if field.onread == OnReadType.rclr:
        return [f"{lhs} <= {_zero_literal(field.width)};"]
    if field.onread == OnReadType.rset:
        return [f"{lhs} <= {_ones_literal(field.width)};"]
    raise NotImplementedError(f"onread={field.onread}")


def field_hwif_in_seq(field: FieldModel, reg: RegModel) -> list[str]:
    """If hw drives the field (hw = w / rw), continuously register hwif_in into
    the field state. RDL permits a write-priority policy; v1 uses hw-low-priority
    (sw writes via the CPU win) by emitting the hwif_in copy unconditionally
    outside the sw-write `if`, and overwriting inside on sw writes."""
    if not field.hw_writable:
        return []
    lhs = f"{reg.state_name}.{field.name}"
    return [f"{lhs} <= hwif_in.{field.hwif_in_name};"]


def field_hwif_out_comb(field: FieldModel, reg: RegModel) -> list[str]:
    if not field.hw_readable:
        return []
    return [f"hwif_out.{field.hwif_out_name} = {reg.state_name}.{field.name};"]


def reg_read_expr(reg: RegModel, data_width: int) -> str:
    """Compose the readback value for a full register, padded to data_width."""
    if not reg.fields:
        return _zero_literal(data_width)

    # Build MSB->LSB by covering all bit positions; any hole becomes zero padding.
    fields_sorted = sorted(reg.fields, key=lambda f: f.lsb, reverse=True)
    parts: list[str] = []
    next_bit = reg.regwidth - 1
    for f in fields_sorted:
        if f.msb < next_bit:
            gap = next_bit - f.msb
            parts.append(f"{gap}'h0")
        if f.sw_readable:
            if f.width == 1:
                parts.append(f"{reg.state_name}.{f.name}")
            else:
                parts.append(f"{reg.state_name}.{f.name}")
        else:
            parts.append(_zero_literal(f.width))
        next_bit = f.lsb - 1
    if next_bit >= 0:
        parts.append(f"{next_bit + 1}'h0")

    if reg.regwidth == data_width:
        # Exact width: if single field covering full width, skip concat
        if len(parts) == 1:
            return parts[0]
        return "{" + ", ".join(parts) + "}"
    # Pad with zeros to data_width
    pad = data_width - reg.regwidth
    body = "{" + ", ".join(parts) + "}"
    if len(parts) == 1:
        body = parts[0]
    return "{" + f"{pad}'h0" + ", " + body + "}"
