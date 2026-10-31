"""Rules that classify the text of a Claude notification.

Kept apart from notifications.py (which depends on WinRT) so it can be tested
and, in the future, turned into configuration.
"""

# Texts that mean "Claude is waiting for you" (English and Portuguese) - includes
# the standard text of Claude Code permission prompts ("Allow Claude to ...")
WAITING_KEYWORDS = ("permission", "permissão", "permissao", "waiting", "aguardando",
                    "approval", "aprovação", "aprovacao", "input needed", "allow claude")

# Background/scheduled-task notifications are not "this conversation" - ignore them
EXCLUDE_KEYWORDS = ("scheduled task",)


def classify(text):
    """Return 'ignore', 'waiting' (waiting for you) or 'done' (response finished)."""
    t = (text or "").lower()
    if any(k in t for k in EXCLUDE_KEYWORDS):
        return "ignore"
    if any(k in t for k in WAITING_KEYWORDS):
        return "waiting"
    return "done"
