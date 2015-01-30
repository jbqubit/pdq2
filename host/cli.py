#!/usr/bin/python
# Robert Jordens <jordens@gmail.com>, 2012

import logging
import numpy as np
from scipy import interpolate

from .pdq2 import Pdq2


def main(dev=None):
    import argparse
    import time

    parser = argparse.ArgumentParser(description="""PDQ2 frontend.
            Evaluates times and voltages, interpolates and uploads
            them.""")
    parser.add_argument("-s", "--serial", default="hwgrep://",
                        help="device url [%(default)s]")
    parser.add_argument("-c", "--channel", default=0, type=int,
                        help="channel: 3*board_num+dac_num [%(default)s]")
    parser.add_argument("-f", "--frame", default=0, type=int,
                        help="frame [%(default)s]")
    parser.add_argument("-e", "--free", default=False, action="store_true",
                        help="software trigger [%(default)s]")
    parser.add_argument("-n", "--disarm", default=False, action="store_true",
                        help="disarm group [%(default)s]")
    parser.add_argument("-t", "--times", default="np.arange(5)*1e-6",
                        help="sample times (s) [%(default)s]")
    parser.add_argument("-v", "--voltages",
                        default="(1-np.cos(t/t[-1]*2*np.pi))/2",
                        help="sample voltages (V) [%(default)s]")
    parser.add_argument("-o", "--order", default=3, type=int,
                        help="interpolation (0: const, 1: lin, 2: quad,"
                        " 3: cubic) [%(default)s]")
    parser.add_argument("-m", "--dcm", default=None, type=int,
                        help="choose fast 100MHz clock [%(default)s]")
    parser.add_argument("-x", "--demo", default=False, action="store_true",
                        help="demo mode: pulse and chirp, 1V*ch+0.1V*frame"
                        " [%(default)s]")
    parser.add_argument("-p", "--plot", help="plot to file [%(default)s]")
    parser.add_argument("-d", "--debug", default=False,
                        action="store_true", help="debug communications")
    parser.add_argument("-r", "--reset", default=False,
                        action="store_true", help="do reset before")
    parser.add_argument("-b", "--bit", default=False,
                        action="store_true", help="do bit test")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    times = eval(args.times, globals(), {})
    voltages = eval(args.voltages, globals(), dict(t=times))

    dev = Pdq2(args.serial, dev)

    if args.reset:
        dev.write(b"\x00")  # flush any escape
        dev.write_cmd("RESET_EN")
        time.sleep(.1)
    if args.dcm:
        dev.write_cmd("DCM_EN")
        dev.freq = 100e6
    elif args.dcm == 0:
        dev.write_cmd("DCM_DIS")
        dev.freq = 50e6
    dev.write_cmd("START_DIS")

    if args.demo:
        channels = [args.channel] if args.channel < dev.num_channels \
            else range(dev.num_channels)
        frames = [args.frame] if args.frame < dev.channel[0].num_frames \
            else range(dev.channel[0].num_frames)
        for channel in channels:
            f = []
            for frame in frames:
                vi = .1*frame + channel + voltages
                pi = 2*np.pi*(.01*frame + .1*channel + 0*voltages)
                fi = 10e6*times/times[-1]
                f.append(b"".join([
                    dev.frame(times, vi, order=args.order, end=False),
                    dev.frame(2*times, voltages, pi, fi, trigger=False),
                    # dev.frame(2*times, 0*vi+.1, 0*pi, 0*fi+1e6),
                    # dev.frame(times, 0*vi, order=args.order, silence=True),
                ]))
            board, dac = divmod(channel, dev.num_dacs)
            dev.write_data(dev.add_mem_header(board, dac, dev.map_frames(f)))
    elif args.bit:
        map = [0] * dev.channels[0].num_frames
        t = np.arange(2*16) * 1.
        v = [-1, 0, -1]
        for i in range(15):
            vi = 1 << i
            v.extend([vi - 1, vi])
        v = np.array(v)*dev.max_out/(1 << 15)
        t, v = t[:3], v[:3]
        # print(t, v)
        for channel in range(dev.num_channels):
            dev.write_mem(channel, dev.multi_frame(
                [(t, v)], channel=channel, order=0, map=map,
                shift=15, stop=False, trigger=False))
    else:
        tv = [(times, voltages)]
        map = [None] * dev.channels[0].num_frames
        map[args.frame] = 0
        dev.write_mem(args.channel, dev.multi_frame(tv, channel=args.channel,
                                       order=args.order, map=map))

    dev.write_cmd("START_EN")
    if not args.disarm:
        dev.write_cmd("ARM_EN")
    if args.free:
        dev.write_cmd("TRIGGER_EN")
    dev.close()

    if args.plot:
        from matplotlib import pyplot as plt
        fig, ax0 = plt.subplots()
        ax0.plot(times, voltages, "xk", label="points")
        if args.order:
            spline = interpolate.splrep(times, voltages, k=args.order)
            ttimes = np.arange(0, times[-1], 1/dev.freq)
            vvoltages = interpolate.splev(ttimes, spline)
            ax0.plot(ttimes, vvoltages, ",b", label="interpolation")
        fig.savefig(args.plot)


if __name__ == "__main__":
    main()
