"""Map SystemRDL nodes to the identifiers used in generated ARCH source."""

from systemrdl.node import FieldNode, RegNode

from .identifier_filter import filter_identifier


def flat_path(node, top) -> str:
    """Return the hierarchical path from `top` to `node`, joined with '_'.

    `top` itself contributes no component — so a register `ctrl` under the top
    addrmap becomes `ctrl`, a field `ctrl.enable` becomes `ctrl_enable`. We
    intentionally do NOT include array indices here: arrays are represented as
    a single Vec-typed reg in the generated ARCH, so the base name is shared
    across all elements (the per-element index lives in the Vec subscript).
    """
    parts: list[str] = []
    cur = node
    while cur is not None and cur is not top:
        parts.append(filter_identifier(cur.inst_name))
        cur = cur.parent
    return "_".join(reversed(parts))


def reg_state_name(reg: RegNode, top) -> str:
    """Instance name for the `reg` declaration holding a register's state."""
    return flat_path(reg, top) + "_r"


def reg_struct_name(reg: RegNode, top) -> str:
    """Struct type name for a register's field layout."""
    return _camel(flat_path(reg, top)) + "Reg"


def field_ident(field: FieldNode) -> str:
    """Field name inside its register's struct."""
    return filter_identifier(field.inst_name)


def csr_enum_variant(reg: RegNode, top) -> str:
    return _camel(flat_path(reg, top))


def _camel(snake: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in snake.split("_") if p)
