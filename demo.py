"""Demonstracao do i-buddy: uma pequena coreografia de ~40 segundos.

Rode com dois cliques no arquivo "Demo.bat" (ou: python demo.py).
"""
import time
from ibuddy import IBuddy, IBuddyNotFoundError
from ibuddy.daemon_client import daemon_paused

# (red, green, blue) na ordem do arco-iris possivel do i-buddy
RAINBOW = [
    ("vermelho", dict(red=True)),
    ("amarelo",  dict(red=True, green=True)),
    ("verde",    dict(green=True)),
    ("ciano",    dict(green=True, blue=True)),
    ("azul",     dict(blue=True)),
    ("roxo",     dict(red=True, blue=True)),
    ("branco",   dict(red=True, green=True, blue=True)),
]


def batimentos(buddy, vezes=4, cor=None):
    """Coracao pulsando, opcionalmente com a cabeca acesa junto."""
    cor = cor or {}
    for _ in range(vezes):
        buddy.set_state(heart=True, **cor)
        time.sleep(0.35)
        buddy.set_state(heart=False, **cor)
        time.sleep(0.35)


def arco_iris(buddy, passo=0.7):
    for nome, cor in RAINBOW:
        print(f"   ... {nome}")
        buddy.set_state(**cor)
        time.sleep(passo)


def bater_asas(buddy, vezes=5, intervalo=0.18, cor=None):
    """Asas batendo com a cabeca colorida junto."""
    cor = cor or {}
    for _ in range(vezes):
        buddy.set_state(wings="up", **cor)
        time.sleep(intervalo)
        buddy.set_state(wings="down", **cor)
        time.sleep(intervalo)


def dancinha(buddy, vezes=3):
    """Gira de um lado para o outro com cores alternadas."""
    for i in range(vezes):
        buddy.set_state(swivel="left", red=True, blue=True, heart=True)
        time.sleep(0.35)
        buddy.set_state(swivel="right", green=True, blue=True, heart=True)
        time.sleep(0.35)


def grand_finale(buddy):
    """Tudo ao mesmo tempo: coracao, cores alternando e asas batendo."""
    for i in range(8):
        _, cor = RAINBOW[i % len(RAINBOW)]
        wings = "up" if i % 2 == 0 else "down"
        buddy.set_state(heart=(i % 2 == 0), wings=wings, **cor)
        time.sleep(0.2)
    # pose final: branco + coracao aceso
    buddy.set_state(heart=True, red=True, green=True, blue=True)
    time.sleep(2.5)


def main():
    print()
    print("=" * 46)
    print("   i-buddy - de volta a vida, 15 anos depois")
    print("=" * 46)
    print()
    try:
        # se o daemon estiver rodando, ele fica quieto durante o show e volta
        # a mostrar a cor de uso da cabeca no final
        with daemon_paused(), IBuddy() as buddy:
            print("1. Batimentos do coracao...")
            batimentos(buddy, vezes=4)

            print("2. Arco-iris de cores...")
            arco_iris(buddy)

            print("3. Batendo asas...")
            bater_asas(buddy, vezes=6)

            print("4. Dancinha...")
            dancinha(buddy, vezes=3)

            print("5. Asas com luz azul...")
            bater_asas(buddy, vezes=5, cor=dict(blue=True))

            print("6. Grand finale!")
            grand_finale(buddy)

            print()
            print("Fim! Obrigado pela paciencia de 15 anos. :)")
    except IBuddyNotFoundError:
        print("i-buddy nao encontrado! Verifique se ele esta conectado na USB.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
