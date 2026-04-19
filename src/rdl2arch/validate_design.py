"""Reject RDL constructs unsupported by the v1 ARCH emitter with actionable errors."""

from systemrdl.node import MemNode, RegNode
from systemrdl.rdltypes import OnReadType, OnWriteType

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
            if fld.node.get_property("intr"):
                raise UnsupportedRdlError(
                    f"interrupt fields not yet supported (v1): '{fld.node.get_path()}'"
                )
            if fld.node.get_property("sticky") or fld.node.get_property("stickybit"):
                raise UnsupportedRdlError(
                    f"sticky fields not yet supported (v1): '{fld.node.get_path()}'"
                )


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
