"""CPU-interface abstraction.

A cpuif supplies ARCH source fragments the emitter stitches into the top module:
the bus declaration, the subordinate port, handshake state/seq/comb fragments,
and the RHS/LHS expressions the field-logic emitter uses to read wdata and
drive rdata.
"""

from abc import ABC, abstractmethod


class CpuifBase(ABC):
    bus_type_name: str = ""
    port_name: str = "s_axi"

    # When True, the emitter drops the sequential `rdata_r` latch and the cpuif
    # drives its read-data output directly from the combinational `rdata_mux`
    # (no cycle of read latency). APB uses this; AXI does not.
    combinational_readback: bool = False

    def __init__(self, addr_width: int, data_width: int) -> None:
        self.addr_width = addr_width
        self.data_width = data_width

    @abstractmethod
    def bus_declaration(self) -> str: ...

    @abstractmethod
    def subordinate_port(self) -> str: ...

    @abstractmethod
    def handshake_state(self) -> str: ...

    @abstractmethod
    def handshake_seq(self) -> str: ...

    @abstractmethod
    def handshake_comb(self) -> str: ...

    @abstractmethod
    def wr_fire_expr(self) -> str: ...

    @abstractmethod
    def rd_fire_expr(self) -> str: ...

    @abstractmethod
    def wr_addr_expr(self) -> str: ...

    @abstractmethod
    def rd_addr_expr(self) -> str: ...

    @abstractmethod
    def wdata_expr(self) -> str: ...
