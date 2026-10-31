"""i-buddy demo: a short ~40 second choreography.

Run it by double-clicking "Demo.bat" (or: python demo.py).
The text printed while it runs is in Portuguese on purpose (it was made as a gift).
"""
import time
from ibuddy import IBuddy, IBuddyNotFoundError
from ibuddy.daemon_client import daemon_paused

# (name shown on screen, head channels): every color the i-buddy can make
RAINBOW = [
    ("vermelho", dict(red=True)),
    ("amarelo",  dict(red=True, green=True)),
    ("verde",    dict(green=True)),
    ("ciano",    dict(green=True, blue=True)),
    ("azul",     dict(blue=True)),
    ("roxo",     dict(red=True, blue=True)),
    ("branco",   dict(red=True, green=True, blue=True)),
]


def heartbeats(buddy, times=4, color=None):
    """Pulse the heart, optionally with the head lit at the same time."""
    color = color or {}
    for _ in range(times):
        buddy.set_state(heart=True, **color)
        time.sleep(0.35)
        buddy.set_state(heart=False, **color)
        time.sleep(0.35)


def rainbow(buddy, step=0.7):
    for name, color in RAINBOW:
        print(f"   ... {name}")
        buddy.set_state(**color)
        time.sleep(step)


def flap_wings(buddy, times=5, interval=0.18, color=None):
    """Flap the wings, optionally with the head lit at the same time."""
    color = color or {}
    for _ in range(times):
        buddy.set_state(wings="up", **color)
        time.sleep(interval)
        buddy.set_state(wings="down", **color)
        time.sleep(interval)


def dance(buddy, times=3):
    """Swivel from side to side with alternating colors."""
    for _ in range(times):
        buddy.set_state(swivel="left", red=True, blue=True, heart=True)
        time.sleep(0.35)
        buddy.set_state(swivel="right", green=True, blue=True, heart=True)
        time.sleep(0.35)


def grand_finale(buddy):
    """Everything at once: heart, cycling colors and flapping wings."""
    for i in range(8):
        _, color = RAINBOW[i % len(RAINBOW)]
        wings = "up" if i % 2 == 0 else "down"
        buddy.set_state(heart=(i % 2 == 0), wings=wings, **color)
        time.sleep(0.2)
    # final pose: white head + heart on
    buddy.set_state(heart=True, red=True, green=True, blue=True)
    time.sleep(2.5)


def main():
    print()
    print("=" * 46)
    print("   i-buddy - de volta a vida, 15 anos depois")
    print("=" * 46)
    print()
    try:
        # if the daemon is running it stays quiet during the show and goes back
        # to showing the usage color on the head at the end
        with daemon_paused(), IBuddy() as buddy:
            print("1. Batimentos do coracao...")
            heartbeats(buddy, times=4)

            print("2. Arco-iris de cores...")
            rainbow(buddy)

            print("3. Batendo asas...")
            flap_wings(buddy, times=6)

            print("4. Dancinha...")
            dance(buddy, times=3)

            print("5. Asas com luz azul...")
            flap_wings(buddy, times=5, color=dict(blue=True))

            print("6. Grand finale!")
            grand_finale(buddy)

            print()
            print("Fim! Obrigado pela paciencia de 15 anos. :)")
    except IBuddyNotFoundError:
        print("i-buddy nao encontrado! Verifique se ele esta conectado na USB.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
