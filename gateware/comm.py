# Robert Jordens <jordens@gmail.com> 2013

from migen.fhdl.std import *
from migen.flow.actor import Sink
from migen.actorlib.structuring import Cast, Pack, pack_layout
from migen.genlib.fsm import FSM, NextState

from .escape import Unescaper
from .ft245r import bus_layout


mem_layout = [("data", 16)]


class MemWriter(Module):
    def __init__(self, board, dacs):
        self.sink = Sink(mem_layout)

        ###

        mems = [dac.parser.mem.get_port(write_capable=True) for dac in dacs]
        self.specials += mems

        dac = Signal(max=len(dacs))
        adr = Signal(16)
        end = Signal(16)
        listen = Signal()
        we = Signal()
        inc = Signal()
        pd = self.sink.payload.data

        self.sink.ack.reset = 1

        self.comb += Array(m.we for m in mems)[dac].eq(we)
        for mem in mems:
            self.comb += [
                    mem.adr.eq(adr),
                    mem.dat_w.eq(pd)
            ]

        self.submodules.fsm = fsm = FSM(reset_state="DEV")
        fsm.act("DEV",
                If(self.sink.stb,
                    NextState("START")
                )
        )
        fsm.act("START",
                If(self.sink.stb,
                    NextState("END")
                )
        )
        fsm.act("END",
                If(self.sink.stb,
                    NextState("DATA")
                )
        )
        fsm.act("DATA",
                If(self.sink.stb,
                    we.eq(listen),
                    inc.eq(1),
                    If(adr == end,
                        NextState("DEV")
                    )
                )
        )

        self.sync += [
                If(fsm.ongoing("DEV"),
                    dac.eq(pd[:4]),
                    listen.eq(pd[4:4+flen(board)] == board),
                ),
                If(fsm.ongoing("START"),
                    adr.eq(pd)
                ),
                If(fsm.ongoing("END"),
                    end.eq(pd)
                ),
                If(fsm.ongoing("DATA"),
                    If(inc,
                        adr.eq(adr + 1)
                    )
                )
        ]


class ResetGen(Module):
    def __init__(self, n=1<<7):
        self.trigger = Signal()
        self.reset = Signal()

        ###

        self.clock_domains.cd_no_rst = ClockDomain(reset_less=True)
        counter = Signal(max=n)
        self.comb += [
                self.cd_no_rst.clk.eq(ClockSignal()),
                self.reset.eq(counter != n - 1)
        ]
        self.sync.no_rst += [
                If(self.trigger,
                    counter.eq(0)
                ).Elif(self.reset,
                    counter.eq(counter + 1)
                ),
        ]


class Ctrl(Module):
    def __init__(self, pads, dacs):
        self.reset = Signal()
        self.dcm_sel = Signal()
        self.sink = Sink(bus_layout)

        ###

        self.sink.ack.reset = 1

        self.submodules.rg = ResetGen()

        # two stage synchronizer for inputs
        frame = Signal.like(pads.frame)
        trigger = Signal()
        arm = Signal()
        start = Signal()
        soft_trigger = Signal()

        self.sync += [
                frame.eq(pads.frame),
                trigger.eq(pads.trigger),
                pads.aux.eq(Cat(*(dac.out.aux for dac in dacs)) != 0),
                #pads.go2_out.eq(
                #    Cat(*(dac.out.sink.stb for dac in dacs)) != 0),
                #pads.go2_out.eq(pads.go2_in), # loop
                #pads.go2_out.eq(0),
        ]
        self.comb += [
                self.reset.eq(self.rg.reset),
                pads.reset.eq(ResetSignal()),
        ]

        for dac in dacs:
            self.sync += [
                    dac.parser.frame.eq(frame),
                    dac.out.trigger.eq(arm & (trigger | soft_trigger)),
                    dac.out.arm.eq(arm),
                    dac.parser.arm.eq(arm),
                    dac.parser.start.eq(start),
            ]

        self.sync += [
                If(self.sink.stb,
                    Case(self.sink.payload.data, {
                        0x00: self.rg.trigger.eq(1),
                        #0x01: self.rg.trigger.eq(0),
                        0x02: soft_trigger.eq(1),
                        0x03: soft_trigger.eq(0),
                        0x04: arm.eq(1),
                        0x05: arm.eq(0),
                        0x06: self.dcm_sel.eq(1),
                        0x07: self.dcm_sel.eq(0),
                        0x08: start.eq(1),
                        0x09: start.eq(0),
                    })
                )
        ]


class Comm(Module):
    def __init__(self, ctrl_pads, dacs):
        self.submodules.unescaper = Unescaper(bus_layout, 0xa5)
        self.sink = self.unescaper.sink
        self.submodules.pack = Pack(bus_layout, 2)
        self.submodules.cast = Cast(pack_layout(bus_layout, 2), mem_layout)
        self.submodules.memwriter = MemWriter(~ctrl_pads.adr, dacs) # adr active low
        self.submodules.ctrl = Ctrl(ctrl_pads, dacs)

        ###

        self.comb += [
                self.pack.sink.connect(self.unescaper.source_a),
                self.cast.sink.connect(self.pack.source),
                self.memwriter.sink.connect(self.cast.source),
                self.ctrl.sink.connect(self.unescaper.source_b),
        ]
