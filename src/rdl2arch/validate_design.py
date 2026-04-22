"""Reject RDL constructs unsupported by the v1 ARCH emitter with actionable errors."""

from systemrdl.node import FieldNode, MemNode, RegNode
from systemrdl.rdltypes import InterruptType, OnReadType, OnWriteType

from .scan_design import DesignModel

_SUPPORTED_ONWRITE = {
    None,
    OnWriteType.woclr,   # write-one-to-clear (RDL "w1c")
    OnWriteType.woset,   # write-one-to-set   (RDL "w1s")
    OnWriteType.wclr,    # any write clears
    OnWriteType.wset,    # any write sets
    OnWriteType.wot,     # write-one-to-toggle (RDL "w1t")
    OnWriteType.wzc,     # write-zero-to-clear (RDL "w0c")
    OnWriteType.wzs,     # write-zero-to-set   (RDL "w0s")
    OnWriteType.wzt,     # write-zero-to-toggle (RDL "w0t")
}

_SUPPORTED_ONREAD = {
    None,
    OnReadType.rclr,
    OnReadType.rset,
}


class UnsupportedRdlError(Exception):
    pass


def validate(design: DesignModel) -> None:
    _reject_unsupported_children(design.top)

    for reg in design.regs:
        # v1: require regwidth 8/16/32, no larger than bus data width
        if reg.regwidth not in (8, 16, 32):
            raise UnsupportedRdlError(
                f"register '{reg.node.get_path()}': v1 only supports regwidth "
                f"8/16/32 (got {reg.regwidth})"
            )
        if reg.regwidth > design.data_width:
            raise UnsupportedRdlError(
                f"register '{reg.node.get_path()}': regwidth {reg.regwidth} "
                f"exceeds bus data width {design.data_width}"
            )
        # v1: 1-D arrays only.
        if reg.node.is_array and len(reg.node.array_dimensions or []) > 1:
            raise UnsupportedRdlError(
                f"multi-dimensional register arrays not yet supported (v1): "
                f"'{reg.node.get_path()}'"
            )
        for fld in reg.fields:
            if fld.onwrite not in _SUPPORTED_ONWRITE:
                raise UnsupportedRdlError(
                    f"field '{fld.node.get_path()}': onwrite={fld.onwrite} "
                    f"not supported in v1"
                )
            if fld.onread not in _SUPPORTED_ONREAD:
                raise UnsupportedRdlError(
                    f"field '{fld.node.get_path()}': onread={fld.onread} "
                    f"not supported in v1"
                )
            if fld.node.get_property("counter"):
                raise UnsupportedRdlError(
                    f"counter fields not yet supported (v1): '{fld.node.get_path()}'"
                )
            _validate_intr_field(fld, reg)


def _reject_unsupported_children(node) -> None:
    for child in node.children(unroll=True):
        if isinstance(child, MemNode):
            raise UnsupportedRdlError(
                f"RDL 'mem' not yet supported: '{child.get_path()}'"
            )
        if isinstance(child, RegNode):
            continue
        if hasattr(child, "children"):
            _reject_unsupported_children(child)


def _validate_intr_field(fld, reg) -> None:
    """Policy for interrupt / sticky fields.

    v1 supports: `intr` fields with `intr type = level` (default),
    optionally with `stickybit` for the latching pattern, and optional
    `->enable` / `->mask` linkage to another FieldNode. Everything else
    is rejected here so users get a clear "not in v1" message rather
    than a confusing downstream error.

    `reg` is the RegModel (not the RegNode) — we only use the RegModel's
    path for error messages; the caller already gated on `reg.node`
    properties.
    """
    node = fld.node
    is_intr = bool(node.get_property("intr") or False)
    is_stickybit = bool(node.get_property("stickybit") or False)
    is_sticky = bool(node.get_property("sticky") or False)

    # `sticky` (field-wide) and `stickybit` (per-bit) are mutually
    # exclusive by RDL; `sticky` treats the whole field as a single
    # latch (clears only when SW clears all bits at once). v1
    # implements per-bit sticky only — it's what virtually every real
    # IRQ_STATUS register uses.
    if is_sticky:
        raise UnsupportedRdlError(
            f"field '{node.get_path()}': field-wide `sticky` not supported "
            f"in v1 — use per-bit `stickybit` instead (the common pattern "
            f"for IRQ_STATUS registers)."
        )

    # halt-output / halt-mask family: separate output signal, semantics
    # distinct from the regular intr output. Not in v1 scope.
    if node.get_property("haltenable") is not None:
        raise UnsupportedRdlError(
            f"field '{node.get_path()}': `haltenable` not supported in v1"
        )
    if node.get_property("haltmask") is not None:
        raise UnsupportedRdlError(
            f"field '{node.get_path()}': `haltmask` not supported in v1"
        )

    if is_intr:
        intr_type = node.get_property("intr type")
        # `intr type = None` and `level` both map to the level-detect
        # default. Edge types need a 1-cycle history of hwif_in, which
        # we don't emit yet.
        if intr_type is not None and intr_type != InterruptType.level:
            raise UnsupportedRdlError(
                f"field '{node.get_path()}': `intr type = {intr_type.name}` "
                f"not supported in v1 — only `level` (default) is implemented. "
                f"Edge-detect requires a previous-cycle capture flop that "
                f"the emitter doesn't generate yet."
            )
        # `enable` / `mask` can reference a FieldNode, a SignalNode, or
        # an integer literal. The FieldNode form is the common
        # companion-register pattern; the others are rejected here so
        # scan_design.py can safely store them as FieldNode|None.
        for prop in ("enable", "mask"):
            target = node.get_property(prop)
            if target is None:
                continue
            if not isinstance(target, FieldNode):
                raise UnsupportedRdlError(
                    f"field '{node.get_path()}': `{prop}` must reference "
                    f"another FieldNode in v1 (got {type(target).__name__}). "
                    f"Signal / integer-literal linkage is not yet supported."
                )
            if target.parent.is_array:
                raise UnsupportedRdlError(
                    f"field '{node.get_path()}': `{prop}` target "
                    f"'{target.get_path()}' lives in an array register, "
                    f"which is not yet supported — v1 only threads scalar "
                    f"companion registers."
                )
    else:
        # `stickybit` without `intr` is legal RDL but has no output on
        # our side — it would produce a latching field with no way to
        # observe the intr contribution. Reject to flag the likely
        # misconfiguration.
        if is_stickybit:
            raise UnsupportedRdlError(
                f"field '{node.get_path()}': `stickybit` without `intr` "
                f"is not supported — sticky latching without the register-"
                f"level intr output has no observable effect in v1."
            )
