"""ARCH reserved-keyword filter for identifiers derived from SystemRDL names."""

ARCH_KEYWORDS = frozenset({
    "and", "arbiter", "assert", "bus", "clkgate", "comb", "cover", "counter",
    "const", "default", "domain", "else", "elsif", "end", "enum", "fifo",
    "for", "fork", "forward", "fsm", "function", "generate", "guard", "hook",
    "if", "implements", "in", "init", "initiator", "inst", "is", "join",
    "kind", "latency", "let", "lifo", "linklist", "lock", "match", "module",
    "not", "on", "op", "or", "out", "package", "param", "pipe_reg", "pipeline",
    "policy", "port", "ports", "ram", "reg", "regfile", "reset", "resource",
    "return", "rising", "seq", "shared", "state", "stage", "stall", "store",
    "struct", "sync", "synchronizer", "target", "template", "thread", "track",
    "true", "false", "unique", "until", "use", "wait", "when", "wire", "with",
    # Built-in types (reserve to avoid collisions with generated identifiers)
    "Bool", "Bit", "UInt", "SInt", "Clock", "Reset", "Vec",
    "SysDomain",
})


def filter_identifier(name: str) -> str:
    """Map an RDL identifier to one safe for ARCH. Suffix `_` on collision."""
    if name in ARCH_KEYWORDS:
        return name + "_"
    return name
