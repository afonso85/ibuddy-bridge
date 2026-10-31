// iBuddy Bridge - service worker.
// Le o uso da janela de 5h da conta Claude usando a sessao ja logada do
// proprio navegador e envia ao daemon do i-buddy. Funciona a partir do
// service worker (nao da pagina) para nao esbarrar no bloqueio Private
// Network Access do Chrome ao falar com o localhost.
//
// Reacao a picos de consumo: em vez de esperar um intervalo fixo (o
// chrome.alarms tem piso de ~1min, insuficiente para "consumindo tokens
// loucamente"), mantemos uma conexao long-poll aberta com o daemon local
// (/wait-activity) que so retorna quando uma resposta termina (ou a cada
// ~25s como pulso de seguranca). Isso tambem mantem o service worker
// "vivo" (fetch pendente reseta o timeout de ociosidade do MV3).
// O alarme de 1min continua como rede de seguranca caso o loop pare.

const DAEMON = "http://127.0.0.1:8765";
const POLL_MINUTES = 1;
const ACTIVITY_TIMEOUT = 25;

function levelFor(util) {
  if (util < 50) return "low";
  if (util < 75) return "medium";
  if (util < 85) return "high";
  return "critical";
}

async function postDaemon(path, body) {
  try {
    await fetch(DAEMON + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  } catch (e) {
    // daemon desligado - tudo bem, ignora silenciosamente
  }
}

async function poll() {
  let usage;
  try {
    const orgs = await fetch("https://claude.ai/api/organizations", {
      credentials: "include",
    }).then((r) => r.json());
    if (!Array.isArray(orgs) || !orgs.length || !orgs[0].uuid) return; // nao logado
    const org = orgs[0].uuid;
    usage = await fetch(`https://claude.ai/api/organizations/${org}/usage`, {
      credentials: "include",
    }).then((r) => r.json());
  } catch (e) {
    return; // sem sessao / offline - nao faz nada
  }

  const fh = usage && usage.five_hour;
  if (!fh || typeof fh.utilization !== "number") return;

  // cor da cabeca conforme % de uso da janela de 5h
  await postDaemon("/token-level", { level: levelFor(fh.utilization) });

  // coracao pulsa quando a janela de 5h renova. Tentamos antes comparar
  // resets_at (o horario ISO do reset), mas essa string jitera por causa
  // de arredondamento no backend - e quando o horario real de reset cai
  // bem em cima de uma virada de minuto, esse jitter cruza a fronteira e
  // dispara falso positivo A CADA poll (foi o que aconteceu: coracao
  // martelando a cada 20-60s). Uso, ao contrario, so sobe dentro de uma
  // janela - uma queda so acontece quando ela renova. Sinal mais direto
  // e sem essa fragilidade de timestamp.
  const { lastUtilization } = await chrome.storage.local.get("lastUtilization");
  if (typeof lastUtilization === "number" && fh.utilization < lastUtilization - 1) {
    await postDaemon("/session-renewed", {});
  }
  await chrome.storage.local.set({ lastUtilization: fh.utilization });
}

let activityLoopRunning = false;

async function activityLoop() {
  if (activityLoopRunning) return; // ja tem um loop rodando, nao duplica
  activityLoopRunning = true;
  let since = 0;
  try {
    while (true) {
      try {
        const r = await fetch(
          `${DAEMON}/wait-activity?since=${since}&timeout=${ACTIVITY_TIMEOUT}`
        );
        const data = await r.json();
        since = typeof data.seq === "number" ? data.seq : since;
        await poll(); // atividade real ou pulso de seguranca - relê o uso
      } catch (e) {
        // daemon desligado - espera um pouco antes de tentar de novo,
        // pra nao girar em loop apertado gastando CPU a toa
        await new Promise((res) => setTimeout(res, 5000));
      }
    }
  } finally {
    activityLoopRunning = false; // nunca deveria chegar aqui (while true)
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("poll", { periodInMinutes: POLL_MINUTES });
  poll();
  activityLoop();
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create("poll", { periodInMinutes: POLL_MINUTES });
  poll();
  activityLoop();
});

chrome.alarms.onAlarm.addListener((a) => {
  if (a.name !== "poll") return;
  poll();
  // rede de seguranca: se o long-poll tiver morrido por algum motivo, reinicia
  if (!activityLoopRunning) activityLoop();
});
