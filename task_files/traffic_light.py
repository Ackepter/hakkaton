"""Переключающийся светофор для UDP-матрицы 64x32."""

import argparse
import math
import socket
import struct
import time


WIDTH, HEIGHT = 64, 32
RADIUS = 10
BLACK = (0, 0, 0)
RED = (255, 0, 0)
YELLOW = (255, 180, 0)
GREEN = (0, 255, 0)


def make_frame(red=False, yellow=False, green=False):
    frame = bytearray(WIDTH * HEIGHT * 3)
    # Матрица установлена вертикально: её координата X становится высотой.
    lamps = ((10, RED, red), (32, YELLOW, yellow), (53, GREEN, green))

    for center_x, color, enabled in lamps:
        if not enabled:
            continue
        for y in range(HEIGHT // 2 - RADIUS - 1, HEIGHT // 2 + RADIUS + 2):
            for x in range(max(0, center_x - RADIUS - 1), min(WIDTH, center_x + RADIUS + 2)):
                coverage = min(1, max(0, RADIUS + 0.5 - math.hypot(x - center_x, y - HEIGHT // 2)))
                if coverage:
                    position = (y * WIDTH + x) * 3
                    frame[position : position + 3] = bytes(round(value * coverage) for value in color)

    return frame


def send_frame(sock, address, frame):
    """Отправляет весь кадр одной UDP-датаграммой для атомарного обновления."""
    sock.sendto(struct.pack("<II", 0, len(frame)) + frame, address)


def show(sock, address, frame, seconds):
    deadline = time.monotonic() + seconds
    while True:
        send_frame(sock, address, frame)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.05, remaining))


def run_cycle(sock, address, red_time, green_time, transition_time, blink_time):
    show(sock, address, make_frame(red=True), red_time)
    show(sock, address, make_frame(red=True, yellow=True), transition_time)
    show(sock, address, make_frame(green=True), green_time)

    for _ in range(3):
        show(sock, address, make_frame(), blink_time)
        show(sock, address, make_frame(green=True), blink_time)

    show(sock, address, make_frame(yellow=True), transition_time)


def main():
    parser = argparse.ArgumentParser(description="Светофор для UDP-матрицы 64x32")
    parser.add_argument("ip", nargs="?", default="192.168.1.198")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--red-time", type=float, default=5)
    parser.add_argument("--green-time", type=float, default=5)
    parser.add_argument("--transition-time", type=float, default=2)
    parser.add_argument("--blink-time", type=float, default=0.5)
    parser.add_argument("--cycles", type=int, default=0, help="0 — повторять бесконечно")
    args = parser.parse_args()

    address = (args.ip, args.port)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("", args.port))
        try:
            cycle = 0
            while args.cycles == 0 or cycle < args.cycles:
                run_cycle(
                    sock,
                    address,
                    args.red_time,
                    args.green_time,
                    args.transition_time,
                    args.blink_time,
                )
                cycle += 1
        except KeyboardInterrupt:
            send_frame(sock, address, make_frame())


if __name__ == "__main__":
    main()
