# iBuddy Bridge

[English](README.md) · **Português**

Transforma o **i-buddy** — a figurinha USB do MSN Messenger (2007) — num painel
físico de notificações para o **app Claude** no Windows: a cabeça mostra o quanto
da janela de 5 horas você já gastou, o coração pulsa quando ela renova, as asas
batem quando uma resposta termina e o corpo gira quando o Claude está esperando
você.

> Projeto **não oficial**, sem vínculo com a Anthropic. A cor da cabeça e o
> coração dependem de um endpoint **interno e não documentado** do `claude.ai`,
> que pode mudar a qualquer momento. Feito para um aparelho de ~15 anos: o
> mecanismo das asas pode falhar de vez em quando (veja *Limitações*).

## O que cada sinal significa

| Sinal | Significado | Origem do dado |
|---|---|---|
| **Cabeça** | Uso da janela de 5 h: verde < 50 %, azul 50–74 %, roxo 75–84 %, vermelho ≥ 85 % | extensão do Chrome |
| **Coração** | A janela de 5 h renovou | extensão do Chrome |
| **Asas** | O Claude terminou uma resposta (qualquer conversa ou aba do app) | notificações do Windows |
| **Giro** | O Claude pediu permissão ou espera sua resposta; repete a cada 60 s, por até 10 min | notificações do Windows |

## Como funciona

```
 app Claude ──notificação──▶ Windows ──▶ ┐
                                         ├──▶  daemon (run_daemon.py) ──HID──▶ i-buddy
 claude.ai ◀──sessão── extensão Chrome ──┘          127.0.0.1:8765
```

- **`ibuddy/driver.py`** — protocolo HID do aparelho (veja [docs/PROTOCOL.pt-BR.md](docs/PROTOCOL.pt-BR.md)).
- **`ibuddy/worker.py`** — dono único do aparelho: fila de comandos, estado
  persistente (cor/coração) por baixo das animações, agendador do giro,
  reconexão automática.
- **`ibuddy/server.py`** — API HTTP local, só em `127.0.0.1`.
- **`ibuddy/notifications.py`** + **`rules.py`** — lê a central de notificações do
  Windows e classifica cada aviso do Claude.
- **`chrome-extension/`** — lê o uso na sessão já logada do Chrome ([detalhes](chrome-extension/README.pt-BR.md)).

## Requisitos

- Windows (testado no 11), Python (testado no 3.13).
- App desktop do Claude (pacote da Microsoft Store) para asas e giro.
- Chrome logado em `claude.ai` para cabeça e coração.
- O i-buddy original, `VID_1130 / PID_0001`.

## Instalação

```
pip install -r requirements.txt
python run_daemon.py
```

1. **Autostart** (sobe o daemon escondido a cada logon):
   `powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1`
   — remova com `-Remove`.
2. **Extensão** (cabeça e coração): `chrome://extensions` → Modo do desenvolvedor →
   *Carregar sem compactação* → pasta `chrome-extension/`.
3. **Notificações**: o Windows pode pedir permissão para o programa ler as
   notificações (Configurações › Privacidade › Notificações). Sem ela, só as asas
   e o giro ficam desativados.

## Testar à mão

```
python demo.py            # coreografia completa (ou dois cliques em Demo.bat)
python cli.py head red    # red green blue cyan yellow purple white off
python cli.py heart on 3
python cli.py flap 5
python cli.py swivel right 3
python cli.py reset
```

Com o daemon rodando, `demo.py` e `cli.py` o pausam durante o comando e, ao
terminar, ele reaplica a cor atual.

## API local

Só `127.0.0.1:8765`. Pedidos vindos de páginas web (cabeçalho `Origin`) ou com
`Host` diferente de `localhost`/`127.0.0.1` são recusados com 403; só extensões
do Chrome e programas locais (curl, Python) passam.

| Rota | Efeito |
|---|---|
| `GET /status` | saúde: conexão, cor, espera, pausa, idade da última escrita no aparelho |
| `GET /wait-activity?since=N&timeout=S` | long-poll: retorna quando uma resposta termina |
| `POST /token-level` `{"level": "low\|medium\|high\|critical\|off"}` | cor da cabeça |
| `POST /session-renewed` `{"times": 3}` | coração pulsa |
| `POST /response-end` `{"times": 5, "interval": 0.2}` | asas batem |
| `POST /waiting-start` · `/waiting-stop` | liga/desliga o modo espera (giro) |
| `POST /swivel-once` `{"pulse_time": 0.5}` | um giro avulso |
| `POST /pause` `{"seconds": 120}` · `/resume` | silencia o daemon (ele reaplica a cor ao voltar) |
| `POST /reset` · `/shutdown` | apaga tudo · encerra o daemon |

## Configuração

- `IBUDDY_DEBUG=1` — log detalhado, **inclui o texto das notificações**. Por
  padrão o log guarda só a classificação, nunca o texto.
- `IBUDDY_APP_AUMID` — se o seu app do Claude tiver outro identificador
  (padrão: `Claude_pzs8sxrjxfjjc!Claude`).
- Constantes de tempo (giro, expiração, reconexão) no topo de `ibuddy/worker.py`;
  palavras que indicam "esperando você" em `ibuddy/rules.py`.

O log fica em `.state/daemon.log` (rotativo, 1 MB × 3) e **não é versionado**.

## Limitações conhecidas

- **Cabeça e coração só atualizam com o Chrome aberto e logado.** Se fechar, a cor congela.
- **Asas dependem de o Windows exibir a notificação de "resposta pronta".** Se
  ela não aparecer (por exemplo, com o app em foco ou no modo Não Perturbe), o
  boneco não bate as asas.
- **O giro não sabe quando você respondeu**: ele desiste sozinho após 10 min.
- **Hooks e statusline do Claude Code não funcionam na aba *Code* do app desktop**
  (testado: nunca foram chamados). Por isso o projeto usa notificações do Windows
  e a extensão.
- O endpoint de uso do `claude.ai` é não oficial.
- O mecanismo das asas de aparelhos antigos pode parar de responder; replugar o
  cabo costuma resolver. Os LEDs não são afetados.

## Solução de problemas

- `curl http://127.0.0.1:8765/status` — `last_write_ok_s_ago` mostra há quanto
  tempo o aparelho aceitou uma escrita; `connected: false` = o daemon está
  tentando reconectar (a cada 30 s).
- `.state/daemon.log` — reconexões, avisos e erros.
- Nada acontece nas asas/giro: confira a permissão de notificações e rode com
  `IBUDDY_DEBUG=1`.

## Testes

```
python -m unittest discover -s tests -v
node tests/extension/test_background.mjs
```

Não tocam no aparelho: usam um dispositivo falso e um relógio controlável.

## Créditos

O protocolo foi levantado a partir de
[py3buddy](https://github.com/armijnhemel/py3buddy) (Armijn Hemel, MIT) e
[pybuddy](https://github.com/ewall/pybuddy) (ewall), e confirmado no hardware.

## Licença

[MIT](LICENSE).
