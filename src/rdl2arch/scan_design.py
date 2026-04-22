"""Walk an elaborated RDL tree and produce a flat design model the emitter consumes."""

from dataclasses import dataclass, field
from typing import Iterator, Optional, Tuple

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


@dataclass
class RegModel:
    node: RegNode
    name: str                 # base identifier (no element suffix), e.g. "ch"
    state_name: str           # `<name>_r`, e.g. "ch_r"
    struct_name: str          # ARCH struct type name shared across array
    enum_variant: str         # base variant name; per-element gets idx suffix
    base_address: int         # absolute byte address of element 0 (or scalar)
    regwidth: int             # in bits
    fields: list[FieldModel] = field(default_factory=list)
    # Array dimensions. Both None for scalar regs; both set for arrays.
    array_count: Optional[int] = None
    array_stride: Optional[int] = None    # bytes between elements
    # Optional side-effect pulse outputs (set via UDPs in `rdl2arch.udps`).
    # See that module's docstring for semantics.
    emit_read_pulse: bool = False
    emit_write_pulse: bool = False

    @property
    def is_array(self) -> bool:
        return self.array_count is not None

    def elements(self) -> Iterator[Tuple[int, int]]:
        """Yield (element_index, byte_address) per instance.

        Scalar regs yield one (0, base_address). Array regs yield N pairs.
        """
        if self.array_count is None:
            yield (0, self.base_address)
        else:
            for i in range(self.array_count):
                yield (i, self.base_address + i * self.array_stride)

    def state_ref(self, elem_idx: int) -> str:
        """Reference to per-element storage. `ch_r` for scalar, `ch_r[2]` for array."""
        if self.array_count is None:
            return self.state_name
        return f"{self.state_name}[{elem_idx}]"

    def enum_variant_for(self, elem_idx: int) -> str:
        """Variant name in the CSR address enum for a specific element."""
        if self.array_count is None:
            return self.enum_variant
        return f"{self.enum_variant}{elem_idx}"

    def hwif_member(self, elem_idx: int, field_name: str) -> str:
        """Per-element hwif member name. `<reg>_<field>` scalar, `<reg>_<i>_<field>` array."""
        if self.array_count is None:
            return f"{self.name}_{field_name}"
        return f"{self.name}_{elem_idx}_{field_name}"


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
         data_width: int = 32,
         addr_width: Optional[int] = None) -> DesignModel:
    """Walk `top` and produce a DesignModel.

    `addr_width`, when supplied, overrides the default derivation
    from the maximum register address. Useful when the regblock sits
    behind a wider bus than its own address footprint needs (caller
    pads), or when a fixture wants a stable width regardless of
    register-map size.
    """
    top_name = top.inst_name
    mod = module_name or _camel(top_name)
    pkg = package_name or (mod + "Pkg")

    regs: list[RegModel] = [_scan_reg(reg, top) for reg in _walk_regs(top)]

    if addr_width is None:
        max_addr = 0
        for r in regs:
            for _, addr in r.elements():
                max_addr = max(max_addr, addr + (r.regwidth // 8) - 1)
        addr_width = max(1, max_addr.bit_length())
    elif addr_width < 1:
        raise ValueError(f"addr_width must be >= 1, got {addr_width}")

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
    """Walk the elaborated tree, yielding one RegNode per declaration.

    `unroll=False` keeps register arrays as a single node (with `is_array`
    set) instead of expanding into N copies. The emitter then represents
    each array as one Vec-typed reg + N address-decoded entries, rather
    than N separately-named scalar regs.
    """
    for child in node.children(unroll=False):
        if isinstance(child, RegNode):
            yield child
        elif isinstance(child, (RegfileNode, AddrmapNode)):
            yield from _walk_regs(child)


def _scan_reg(reg: RegNode, top: AddrmapNode) -> RegModel:
    array_count: Optional[int] = None
    array_stride: Optional[int] = None
    if reg.is_array:
        dims = reg.array_dimensions or []
        if len(dims) == 1:
            array_count = int(dims[0])
        array_stride = int(reg.array_stride) if reg.array_stride else (reg.get_property("regwidth") // 8)
        # `absolute_address` errors on unrolled arrays (no concrete index);
        # combine parent absolute + raw offset to get element-0 address.
        base_address = reg.parent.absolute_address + reg.raw_address_offset
    else:
        base_address = reg.absolute_address

    m = RegModel(
        node=reg,
        name=deref.flat_path(reg, top),
        state_name=deref.reg_state_name(reg, top),
        struct_name=deref.reg_struct_name(reg, top),
        enum_variant=deref.csr_enum_variant(reg, top),
        base_address=base_address,
        regwidth=reg.get_property("regwidth"),
        array_count=array_count,
        array_stride=array_stride,
        emit_read_pulse=_get_optional_udp_bool(reg, "emit_read_pulse"),
        emit_write_pulse=_get_optional_udp_bool(reg, "emit_write_pulse"),
    )
    for fnode in reg.fields():
        m.fields.append(_scan_field(fnode))
    return m


def _scan_field(f: FieldNode) -> FieldModel:
    return FieldModel(
        node=f,
        name=deref.field_ident(f),
        msb=f.msb,
        lsb=f.lsb,
        width=f.width,
        sw_readable=f.is_sw_readable,
        sw_writable=f.is_sw_writable,
        hw_readable=f.is_hw_readable,
        hw_writable=f.is_hw_writable,
        reset=int(f.get_property("reset") or 0),
        onwrite=f.get_property("onwrite"),
        onread=f.get_property("onread"),
    )


def _camel(snake: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in snake.split("_") if p)


def _get_optional_udp_bool(node, name: str) -> bool:
    """Read a boolean UDP, returning False if the UDP isn't registered.

    Makes rdl2arch's optional UDPs (see `rdl2arch.udps`) truly optional:
    callers who don't use them don't need to call `register_udp` at all.
    """
    try:
        return bool(node.get_property(name) or False)
    except LookupError:
        return False
