#!/usr/bin/env python3
"""
dmx_monitor.py - Verify DMX output without an Enttec USB-to-DMX device.

PiMediaSync drives DMX through pySimpleDMX, which speaks the Enttec USB Pro
serial protocol. This script lets you confirm that output is correct without
any physical DMX hardware by reading and decoding that serial stream.

Typical workflow (no hardware required)
---------------------------------------
1. Install socat:
       sudo apt install socat

2. Create a linked pair of virtual serial ports. socat prints two device
   paths (e.g. /dev/pts/3 and /dev/pts/4). Leave this running:
       socat -d -d pty,raw,echo=0 pty,raw,echo=0

3. Point DMX_DEVICE in your config at ONE of the ports, e.g.:
       DMX_DEVICE = "/dev/pts/3"

4. Run this monitor on the OTHER port (keep it running for the whole test):
       python3 scripts/dmx_monitor.py /dev/pts/4

5. In another terminal, run the app against the same config:
       ./app.py -d -c your_config.py

   As the lighting sequence plays you'll see channel values update live.

IMPORTANT: keep this monitor running while the app is talking to the virtual
port. pySimpleDMX reboots the host if a serial write times out
(rebootIfComFailure defaults to True); draining the port here prevents that.

Enttec USB Pro "Send DMX" packet decoded here:
    0x7E, 0x06 (label), len_lo, len_hi, <frame bytes>, 0xE7
The frame is 1-indexed by DMX channel (index 0 is unused, no 0x00 start code).
"""

import argparse
import sys
from datetime import datetime

try:
    import serial
except ImportError:
    sys.exit("pyserial is required: pip3 install pyserial "
             "(it is normally installed as a pySimpleDMX dependency).")

START_VAL = 0x7E
END_VAL = 0xE7
TX_DMX_PACKET = 0x06
DEFAULT_BAUD = 57600  # matches pySimpleDMX COM_BAUD


def read_exact(port, n):
    """Read exactly n bytes (blocking), or return None on EOF/timeout."""
    buf = bytearray()
    while len(buf) < n:
        chunk = port.read(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def decode_packets(port, show_all):
    last_frame = {}
    frame_count = 0

    while True:
        # Resynchronise on the start byte.
        b = port.read(1)
        if not b:
            continue
        if b[0] != START_VAL:
            continue

        header = read_exact(port, 3)  # label + length (little-endian)
        if header is None:
            continue
        label = header[0]
        length = header[1] | (header[2] << 8)

        data = read_exact(port, length)
        if data is None:
            continue

        tail = read_exact(port, 1)
        if tail is None or tail[0] != END_VAL:
            print("  [warn] malformed packet (bad end byte), resyncing")
            continue
        if label != TX_DMX_PACKET:
            continue  # not a DMX send packet

        frame_count += 1
        # Channel 1 maps to data index 1 (index 0 is unused).
        current = {ch: data[ch] for ch in range(1, length)}

        if show_all:
            changed = current
        else:
            changed = {ch: v for ch, v in current.items()
                       if last_frame.get(ch, 0) != v}

        if changed:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            pretty = " ".join("ch{}={}".format(ch, v)
                              for ch, v in sorted(changed.items()))
            print("[{}] frame {:>5}  {}".format(ts, frame_count, pretty))

        last_frame = current


def main():
    parser = argparse.ArgumentParser(
        description="Decode and print the DMX serial stream produced by "
                    "PiMediaSync / pySimpleDMX (Enttec USB Pro protocol).")
    parser.add_argument("port",
        help="serial port to read (e.g. a socat PTY like /dev/pts/4, "
             "or a real /dev/ttyUSB0)")
    parser.add_argument("-b", "--baud", type=int, default=DEFAULT_BAUD,
        help="baud rate (default: {}, matching pySimpleDMX)".format(DEFAULT_BAUD))
    parser.add_argument("-a", "--all", action="store_true",
        help="print every channel on every frame (default: only changes)")
    args = parser.parse_args()

    try:
        port = serial.Serial(args.port, args.baud, timeout=1)
    except serial.SerialException as e:
        sys.exit("Could not open {}: {}".format(args.port, e))

    print("Listening for DMX frames on {} at {} baud "
          "(Ctrl+C to stop)...".format(args.port, args.baud))
    try:
        decode_packets(port, args.all)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        port.close()


if __name__ == "__main__":
    main()
