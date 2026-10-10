"""Provider-specific mailbox identity; preserve delivery addresses separately."""


def canonical_mailbox(email: str) -> str:
    local, _, domain = email.strip().lower().partition("@")
    # Other domains may assign dots or plus characters to distinct mailboxes.
    if domain in {"gmail.com", "googlemail.com"}:
        domain = "gmail.com"
        local = local.split("+", 1)[0].replace(".", "")
    return f"{local}@{domain}"
