# iBuddy Bridge — extensão do Chrome

[English](README.md) · **Português**

Lê o uso da **janela de 5 horas** da sua conta Claude (o mesmo número da aba
"Uso" do app) e avisa o daemon do i-buddy, para a cabeça mudar de cor conforme o
consumo e o coração pulsar quando a janela renova.

## Como funciona

- Usa a sessão que **já está logada** no seu Chrome (como os trackers de uso que
  existem na loja): sem token, sem senha, sem cofre.
- Faz duas leituras em `claude.ai`: `/api/organizations` e
  `/api/organizations/{id}/usage`. **Esse endpoint não é documentado nem
  oficial** — pode mudar ou quebrar sem aviso.
- A **única coisa que sai** da extensão é o nível (`low`/`medium`/`high`/`critical`)
  enviado ao daemon em `127.0.0.1:8765`. Nada vai para a internet.
- Roda no *service worker* da extensão (e não na página) para conseguir falar com
  o `localhost` sem o bloqueio de *Private Network Access* do Chrome.
- Em vez de consultar a cada X minutos, mantém uma conexão aberta com o daemon
  (`/wait-activity`) que só retorna quando uma resposta termina (ou a cada ~25 s,
  como pulso de segurança). Assim a cor reage logo após um pico de consumo, sem
  martelar o `claude.ai`. Um alarme de 1 minuto continua como rede de segurança.

## Instalação (uma vez)

1. Abra `chrome://extensions` e ligue o **Modo do desenvolvedor**.
2. Clique em **Carregar sem compactação** e selecione esta pasta
   (`chrome-extension/`, dentro do repositório).
3. Fique logado em `claude.ai` e deixe o daemon rodando.

Depois de editar `background.js`, recarregue a extensão (botão ↻ no card).

## Cores

| Uso da janela de 5 h | Cabeça |
|---|---|
| menos de 50 % | verde |
| 50 a 74 % | azul |
| 75 a 84 % | roxo |
| 85 % ou mais | vermelho |

O coração pulsa quando o uso **cai** de uma leitura para a outra (dentro de uma
janela o uso só sobe; queda = a janela renovou). Comparar o horário `resets_at`
não funciona: a API devolve esse valor com ruído de milissegundos, e quando o
horário real cai perto de uma virada de minuto o ruído cruza a fronteira e
dispara um falso positivo a cada leitura.

## Limitação

Só atualiza com o Chrome aberto e logado. Se fechar o Chrome, a cabeça mantém a
última cor lida mas passa a piscar após 5 minutos (é o jeito do daemon avisar que o
valor está velho).

## Testes

```
node tests/extension/test_background.mjs
```
