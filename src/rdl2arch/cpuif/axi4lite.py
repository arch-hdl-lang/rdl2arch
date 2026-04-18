"""AXI4-Lite subordinate CPU interface."""

import textwrap

from .base import CpuifBase


class AXI4Lite_Cpuif(CpuifBase):
    bus_type_name = "AxiLite"
    port_name = "s_axi"

    def bus_declaration(self) -> str:
        strb_w = self.data_width // 8
        return textwrap.dedent(f"""\
            bus {self.bus_type_name}
              param ADDR_W: const = {self.addr_width};
              param DATA_W: const = {self.data_width};

              aw_valid: out Bool;
              aw_ready: in  Bool;
              aw_addr:  out UInt<ADDR_W>;
              aw_prot:  out UInt<3>;

              w_valid:  out Bool;
              w_ready:  in  Bool;
              w_data:   out UInt<DATA_W>;
              w_strb:   out UInt<{strb_w}>;

              b_valid:  in  Bool;
              b_ready:  out Bool;
              b_resp:   in  UInt<2>;

              ar_valid: out Bool;
              ar_ready: in  Bool;
              ar_addr:  out UInt<ADDR_W>;
              ar_prot:  out UInt<3>;

              r_valid:  in  Bool;
              r_ready:  out Bool;
              r_data:   in  UInt<DATA_W>;
              r_resp:   in  UInt<2>;
            end bus {self.bus_type_name}""")

    def subordinate_port(self) -> str:
        return (f"  port {self.port_name}: target "
                f"{self.bus_type_name}<ADDR_W={self.addr_width}, "
                f"DATA_W={self.data_width}>;")

    # --- handshake wiring ----------------------------------------------------
    # Strategy: single-outstanding write and read. Accept AW+W simultaneously;
    # hold B until master raises B_READY. Accept AR; hold R until R_READY.
    def handshake_state(self) -> str:
        p = self.port_name
        return textwrap.dedent(f"""\
              reg bresp_valid_r: Bool reset rst => false;
              reg rresp_valid_r: Bool reset rst => false;
              reg rdata_r:       UInt<{self.data_width}> reset rst => 0;

              let wr_fire: Bool = {p}.aw_valid and {p}.w_valid and not bresp_valid_r;
              let rd_fire: Bool = {p}.ar_valid and not rresp_valid_r;""")

    def handshake_seq(self) -> str:
        """Seq block assignments for handshake latches. Inserted inside the
        regblock's write/read seq block around the field logic."""
        p = self.port_name
        return textwrap.dedent(f"""\
                if bresp_valid_r and {p}.b_ready
                  bresp_valid_r <= false;
                end if
                if wr_fire
                  bresp_valid_r <= true;
                end if
                if rresp_valid_r and {p}.r_ready
                  rresp_valid_r <= false;
                end if
                if rd_fire
                  rresp_valid_r <= true;
                end if""")

    def handshake_comb(self) -> str:
        """Comb block assignments for the subordinate handshake outputs."""
        p = self.port_name
        return textwrap.dedent(f"""\
                {p}.aw_ready = not bresp_valid_r;
                {p}.w_ready  = not bresp_valid_r;
                {p}.b_valid  = bresp_valid_r;
                {p}.b_resp   = 0;

                {p}.ar_ready = not rresp_valid_r;
                {p}.r_valid  = rresp_valid_r;
                {p}.r_data   = rdata_r;
                {p}.r_resp   = 0;""")

    # --- expressions used by the field emitter --------------------------------
    def wr_fire_expr(self) -> str:
        return "wr_fire"

    def rd_fire_expr(self) -> str:
        return "rd_fire"

    def wr_addr_expr(self) -> str:
        return f"{self.port_name}.aw_addr"

    def rd_addr_expr(self) -> str:
        return f"{self.port_name}.ar_addr"

    def wdata_expr(self) -> str:
        return f"{self.port_name}.w_data"
