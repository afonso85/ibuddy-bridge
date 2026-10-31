# Protocolo USB do i-buddy

Notas de engenharia reversa confirmadas **no hardware real** (Tenx Technology,
USB `VID_1130` / `PID_0001`, string de produto `Tenx USBOUTDEVICE DEMO`).
A implementação de referência deste repositório é [`ibuddy/driver.py`](../ibuddy/driver.py);
a função pura `build_command()` e os testes em
[`tests/test_driver.py`](../tests/test_driver.py) fixam os bytes abaixo.

## Dispositivo

- Classe HID: o Windows carrega o driver HID genérico sozinho — **não é preciso
  instalar driver, nem trocar por WinUSB/libusb (Zadig)**.
- Expõe **duas interfaces HID** (`MI_00` e `MI_01`). **Só a `MI_01` (índice 1)
  responde.**
- Output report de 9 bytes: report ID `0` + 8 bytes de dados.

## Cada comando = dois reports em sequência

Enviados com `HidD_SetOutputReport` (em Python, `pywinusb`:
`dev.send_output_report([0] + dados)`), um logo após o outro:

| Ordem | Dados (8 bytes) | Função |
|---|---|---|
| 1 | `22 09 00 02 01 00 00 00` | SETUP, constante |
| 2 | `55 53 42 43 00 40 02 <cmd>` | MESSAGE: assinatura `"USBC"` + byte de comando |

Sem a assinatura (ou sem o SETUP antes), o firmware **ignora tudo em silêncio**
— sem erro algum. Foi assim que "mandar `0xFF` em tudo" não fazia nada.

## Byte de comando

Bitfield **ativo em zero**: `0xFF` é o estado neutro (tudo apagado, sem movimento);
zerar um bit liga o recurso.

| Bit | Recurso | Observação |
|---|---|---|
| 7 | Coração | LED vermelho fixo (liga/desliga) |
| 6 | Cabeça — azul | |
| 5 | Cabeça — verde | |
| 4 | Cabeça — vermelho | |
| 3 | Asas — pulso "para cima" | |
| 2 | Asas — pulso "para baixo" | |
| 1 | Giro — direita | |
| 0 | Giro — esquerda | |

Valores conferidos fisicamente: `0x7F` coração · `0xEF` cabeça vermelha ·
`0xF7` asas para cima · `0xFB` asas para baixo · `0xFD` giro à direita ·
`0x0F` coração + cabeça branca.

## Comportamento físico

- **Cabeça**: cada canal só liga ou desliga (sem PWM), então há 7 cores:
  vermelho, verde, azul, amarelo (R+G), ciano (G+B), roxo (R+B) e branco. No
  aparelho testado o "amarelo" sai esverdeado, porque o LED verde é mais forte.
- **Asas**: manter um estado fixo **não move nada**. Para bater é preciso
  alternar "para cima"/"para baixo" a cada ~0,2 s (comporta-se como solenoide).
- **Giro**: cada pulso gira um ângulo pequeno e incremental.
- Combinações valem: o mesmo byte pode ter coração, cor, asas e giro ao mesmo tempo.

## Armadilhas

- **Alça HID morta com o aparelho ainda presente.** Em pleno uso, uma escrita
  pode falhar com `HIDError: Error device disconnected before write` enquanto o
  Windows ainda enumera o dispositivo (típico de suspensão seletiva da porta
  USB). A saída é descartar a alça e reabrir; não precisa replugar.
- **Mecanismo das asas em unidades antigas.** Pode deixar de responder depois de
  muita atuação (os LEDs seguem normais). Replugar o cabo costuma restaurar.
- **Vários processos.** Duas alças abertas ao mesmo tempo funcionam, mas os
  comandos se misturam — por isso o daemon é o dono único do aparelho
  (`ibuddy/worker.py`) e `cli.py`/`demo.py` o pausam enquanto rodam.
- Só o `PID_0001` foi testado. O projeto de referência `py3buddy` menciona
  outros PIDs (`0002`, `0004`, `0005`) para variantes do produto.

## Origem

Os bytes foram identificados a partir de dois projetos abertos que usam
transferências de controle via libusb (`bmRequestType 0x21`, `bRequest 0x09`,
`wValue 2`, `wIndex 1`) e depois **confirmados e adaptados** ao caminho HID
padrão do Windows:

- [armijnhemel/py3buddy](https://github.com/armijnhemel/py3buddy) (MIT)
- [ewall/pybuddy](https://github.com/ewall/pybuddy)
