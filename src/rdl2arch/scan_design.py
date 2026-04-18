"""Walk an elaborated RDL tree and produce a flat design model the emitter consumes."""

from dataclasses import dataclass, field
from typing import Optional

from systemrdl.node import AddrmapNode, FieldNode, RegfileNode, RegNode
from systemrdl.rdltypes import OnReadType, OnWriteType

from . import dereferencer as deref


@dataclass
class FieldModel:
    node: FieldNode
    name: str                 # identifier inside the register struct
    msb: int
    lsb: int
    width: int
    sw_readable: bool
    sw_writable: bool
    hw_readable: bool         # exposed as hwif_out (hw reads field state)
    hw_writable: bool         # exposed as hwif_in (hw drives field state)
    reset: int
    onwrite: Optional[OnWriteType]
    onread: Optional[OnReadType]
    hwif_out_name: str        # full path used as hwif_out struct member
    hwif_in_name: str         # full path used as hwif_in struct member


@dataclass
class RegModel:
    node: RegNode
    name: str                 # identifier for `reg <name>_r` instance (minus _r)
    state_name: str           # `<name>_r`
    struct_name: str          # ARCH struct type name
    enum_variant: str         # variant in the CSR address enum
    address: int              # absolute byte address
    regwidth: int             # in bits
    fields: list[FieldModel] = field(default_factory=list)


@dataclass
class DesignModel:
    top: AddrmapNode
    module_name: str          # ARCH module name
    package_name: str         # ARCH package name
    hwif_in_struct: str
    hwif_out_struct: str
    csr_enum_name: str
    addr_width: int
    data_width: int
    regs: list[RegModel] = field(default_factory=list)


def scan(top: AddrmapNode, *, module_name: Optional[str] = None,
         package_name: Optional[str] = None,
         data_width: int = 32) -> DesignModel:
    top_name = top.inst_name
    mod = module_name or _camel(top_name)
    pkg = package_name or (mod + "Pkg")

    regs: list[RegModel] = []
    for reg in _walk_regs(top):
        regs.append(_scan_reg(reg, top))

    max_addr = max((r.address + (r.regwidth // 8) - 1 for r in regs), default=0)
    addr_width = max(1, max_addr.bit_length())

    return DesignModel(
        top=top,
        module_name=mod,
        package_name=pkg,
        hwif_in_struct=mod + "HwifIn",
        hwif_out_struct=mod + "HwifOut",
        csr_enum_name=mod + "Csr",
        addr_width=addr_width,
        data_width=data_width,
        regs=regs,
    )


def _walk_regs(node):
    for child in node.children(unroll=True):
        if isinstance(child, RegNode):
            yield child
        elif isinstance(child, (RegfileNode, AddrmapNode)):
            yield from _walk_regs(child)


def _scan_reg(reg: RegNode, top: AddrmapNode) -> RegModel:
    m = RegModel(
        node=reg,
        name=deref.flat_path(reg, top),
        state_name=deref.reg_state_name(reg, top),
        struct_name=deref.reg_struct_name(reg, top),
        enum_variant=deref.csr_enum_variant(reg, top),
        address=reg.absolute_address,
        regwidth=reg.get_property("regwidth"),
    )
    for fnode in reg.fields():
        m.fields.append(_scan_field(fnode, top))
    return m


def _scan_field(f: FieldNode, top: AddrmapNode) -> FieldModel:
    msb = f.msb
    lsb = f.lsb
    width = f.width
    return FieldModel(
        node=f,
        name=deref.field_ident(f),
        msb=msb,
        lsb=lsb,
        width=width,
        sw_readable=f.is_sw_readable,
        sw_writable=f.is_sw_writable,
        hw_readable=f.is_hw_readable,
        hw_writable=f.is_hw_writable,
        reset=int(f.get_property("reset") or 0),
        onwrite=f.get_property("onwrite"),
        onread=f.get_property("onread"),
        hwif_out_name=deref.hwif_out_member(f, top),
        hwif_in_name=deref.hwif_in_member(f, top),
    )


def _camel(snake: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in snake.split("_") if p)
