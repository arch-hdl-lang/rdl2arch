"""APB4 subordinate CPU interface.

APB is a 2-phase interface:
  - Setup phase:  psel=1, penable=0
  - Access phase: psel=1, penable=1 (transfer completes when pready=1)

The generated regblock responds in one cycle: pready is raised the same cycle
penable rises. Single-outstanding by construction.
"""

import textwrap

from .base import CpuifBase


class APB4_Cpuif(CpuifBase):
    bus_type_name = "Apb4"
    port_name = "s_apb"
    combinational_readback = True

    def bus_declaration(self) -> str:
        strb_w = self.data_width // 8
        return textwrap.dedent(f"""\
            bus {self.bus_type_name}
              param ADDR_W: const = {self.addr_width};
              param DATA_W: const = {self.data_width};

              psel:    out Bool;
              penable: out Bool;
              pwrite:  out Bool;
              paddr:   out UInt<ADDR_W>;
              pwdata:  out UInt<DATA_W>;
              pstrb:   out UInt<{strb_w}>;
              pprot:   out UInt<3>;

              pready:  in  Bool;
              prdata:  in  UInt<DATA_W>;
              pslverr: in  Bool;
            end bus {self.bus_type_name}""")

    def subordinate_port(self) -> str:
        return (f"  port {self.port_name}: target "
                f"{self.bus_type_name}<ADDR_W={self.addr_width}, "
                f"DATA_W={self.data_width}>;")

    def handshake_state(self) -> str:
        # APB completes in one access phase — no persistent handshake state.
        # Read-data is combinational (pulled straight from rdata_mux).
        return textwrap.dedent(f"""\
              let access: Bool = {self.port_name}.psel and {self.port_name}.penable;
              let wr_fire: Bool = access and {self.port_name}.pwrite;
              let rd_fire: Bool = access and not {self.port_name}.pwrite;""")

    def handshake_seq(self) -> str:
        return ""

    def handshake_comb(self) -> str:
        p = self.port_name
        return textwrap.dedent(f"""\
                {p}.pready  = true;
                {p}.prdata  = rdata_mux;
                {p}.pslverr = false;""")

    def wr_fire_expr(self) -> str:
        return "wr_fire"

    def rd_fire_expr(self) -> str:
        return "rd_fire"

    def wr_addr_expr(self) -> str:
        return f"{self.port_name}.paddr"

    def rd_addr_expr(self) -> str:
        return f"{self.port_name}.paddr"

    def wdata_expr(self) -> str:
        return f"{self.port_name}.pwdata"
