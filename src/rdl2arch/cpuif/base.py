"""CPU-interface abstraction.

A cpuif supplies ARCH source fragments the emitter stitches into the top module:
the bus declaration, the subordinate port, handshake state/seq/comb fragments,
and the RHS/LHS expressions the field-logic emitter uses to read wdata and
drive rdata.
"""

from abc import ABC, abstractmethod
from typing import Optional


class CpuifBase(ABC):
    bus_type_name: str = ""
    # Class-level defaults — subclasses override. Users can override per-
    # instance via the `port_name=` / `combinational_readback=` ctor kwargs
    # (threaded from `rdl2arch.toml` or from Python-API call sites).
    port_name: str = "s_axi"

    # When True, the emitter drops the sequential `rdata_r` latch and the cpuif
    # drives its read-data output directly from the combinational `rdata_mux`
    # (no cycle of read latency). APB uses this; AXI does not.
    combinational_readback: bool = False

    def __init__(
        self,
        addr_width: int,
        data_width: int,
        *,
        port_name: Optional[str] = None,
        combinational_readback: Optional[bool] = None,
    ) -> None:
        self.addr_width = addr_width
        self.data_width = data_width
        # Instance-level override shadows the class attr when provided.
        # Assigning to `self.port_name` creates an instance attr that
        # takes precedence over `type(self).port_name` for attribute
        # lookup — existing subclass class attrs are untouched, so
        # callers who don't pass the kwarg see the historical default.
        if port_name is not None:
            self.port_name = port_name
        if combinational_readback is not None:
            self.combinational_readback = combinational_readback

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
