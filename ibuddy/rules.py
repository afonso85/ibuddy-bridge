"""Regras que classificam o texto de uma notificacao do Claude.

Fica separado de notifications.py (que depende do WinRT) para ser testavel e
para, no futuro, virar configuracao.
"""

# textos que indicam "Claude esta esperando voce" (pt e en) - inclui o texto
# padrao dos prompts de permissao do Claude Code ("Allow Claude to ...")
WAITING_KEYWORDS = ("permission", "permissão", "permissao", "waiting", "aguardando",
                    "approval", "aprovação", "aprovacao", "input needed", "allow claude")

# notificacoes de rotina/tarefa agendada nao sao "esta conversa" - ignora
EXCLUDE_KEYWORDS = ("scheduled task",)


def classify(text):
    """Devolve 'ignore', 'waiting' (esperando voce) ou 'done' (resposta concluida)."""
    t = (text or "").lower()
    if any(k in t for k in EXCLUDE_KEYWORDS):
        return "ignore"
    if any(k in t for k in WAITING_KEYWORDS):
        return "waiting"
    return "done"
