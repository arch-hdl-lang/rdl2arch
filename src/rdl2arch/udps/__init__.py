"""User-defined RDL properties consumed by rdl2arch.

These are OPTIONAL — the emitter works without any UDPs for the
standard sw/hw register semantics. Tag a reg with one of these UDPs
to get an additional side-effect output port:

- `emit_read_pulse  = true;` — adds `<reg>_read_pulse: out Bool` that
                               fires for one cycle on every SW read
                               that hits this register's address.
- `emit_write_pulse = true;` — adds `<reg>_write_pulse: out Bool` that
                               fires for one cycle on every SW write
                               that hits this register's address.

Common use-cases:
- FIFO pop-on-read (read_pulse → drops one entry from a sidecar FIFO).
- Clear-on-read status registers whose hw-driven value needs to be
  latched when SW observes it.
- Interrupt-controller claim/complete handshake (SW reads claim → HW
  latches which source was claimed; SW writes complete → HW clears
  the latch).

To use, register them with the RDL compiler before compiling the spec:

    from systemrdl import RDLCompiler
    from rdl2arch.udps import ALL_UDPS

    rdlc = RDLCompiler()
    for udp in ALL_UDPS:
        rdlc.register_udp(udp, soft=False)
    rdlc.compile_file("my.rdl")
"""

from systemrdl.component import Reg
from systemrdl.udp import UDPDefinition


class EmitReadPulse(UDPDefinition):
    name = "emit_read_pulse"
    valid_components = {Reg}
    valid_type = bool


class EmitWritePulse(UDPDefinition):
    name = "emit_write_pulse"
    valid_components = {Reg}
    valid_type = bool


ALL_UDPS = [EmitReadPulse, EmitWritePulse]

__all__ = ["ALL_UDPS", "EmitReadPulse", "EmitWritePulse"]
