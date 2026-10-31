"""CLI simples para testar o i-buddy manualmente.

Exemplos:
    python cli.py heart on [segundos]     (padrao: 2s)
    python cli.py head red                (red green blue cyan yellow purple white off)
    python cli.py flap 5
    python cli.py swivel right 3
    python cli.py reset

Com o daemon rodando, ele e silenciado durante o comando e reaplica a cor
atual da cabeca no fim (ver ibuddy/daemon_client.py).
"""
import sys
import time

from ibuddy import IBuddy, IBuddyNotFoundError
from ibuddy.daemon_client import daemon_paused

COLORS = {
    "red": dict(red=True),
    "green": dict(green=True),
    "blue": dict(blue=True),
    "cyan": dict(green=True, blue=True),
    "yellow": dict(red=True, green=True),
    "purple": dict(red=True, blue=True),
    "white": dict(red=True, green=True, blue=True),
    "off": dict(),
}


def run(action, args):
    with IBuddy() as buddy:
        if action == "heart":
            on = (args[0] if args else "on") == "on"
            seconds = float(args[1]) if len(args) > 1 else 2.0
            buddy.heart(on)
            if on:
                time.sleep(seconds)
        elif action == "head":
            color = args[0] if args else "off"
            if color not in COLORS:
                print(f"Cor invalida: {color}. Opcoes: {list(COLORS)}")
                raise SystemExit(1)
            buddy.head_color(**COLORS[color])
            if color != "off":
                time.sleep(2)
        elif action == "flap":
            buddy.flap(times=int(args[0]) if args else 3)
        elif action == "swivel":
            direction = args[0] if args else "right"
            pulses = int(args[1]) if len(args) > 1 else 1
            buddy.swivel(direction, pulses=pulses)
        elif action == "reset":
            buddy.reset()
        else:
            print(f"Acao desconhecida: {action}")
            print(__doc__)
            raise SystemExit(1)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    try:
        with daemon_paused():
            run(sys.argv[1], sys.argv[2:])
    except IBuddyNotFoundError as e:
        print(f"Erro: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
