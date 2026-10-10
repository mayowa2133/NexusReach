"""Bounded HTML parsing shared by public pages and exact-job adapters."""

from lxml import etree

MAX_HTML_CHARS = 5 * 1024 * 1024


def document(value: str) -> etree._Element | None:
    # Never enable huge_tree or network access for attacker-controlled pages.
    if len(value) > MAX_HTML_CHARS:
        raise ValueError("HTML exceeds the parsing limit")
    return etree.HTML(value, parser=etree.HTMLParser(no_network=True, recover=True))


def text(value: str, *, remove_scripts: bool = True) -> str:
    root = document(value)
    if root is None:
        return ""
    parts = []
    walker = etree.iterwalk(root, events=("start", "end"))
    for event, node in walker:
        if event == "start":
            if remove_scripts and node.tag in {"script", "style"}:
                walker.skip_subtree()
            elif node.text:
                parts.append(node.text)
        elif node.tail:
            parts.append(node.tail)
    return " ".join(" ".join(parts).split())


def element_text(value: str, tag: str) -> str:
    root = document(value)
    if root is None:
        return ""
    node = next(root.iter(tag), None)
    return " ".join("".join(node.itertext()).split())[:4096] if node is not None else ""


def page(value: str) -> dict[str, str]:
    return {"title": element_text(value, "title"), "content": text(value)}


async def page_async(value: str) -> dict[str, str]:
    from app.utils.sandboxed_process import run_in_sandbox_async

    # A network timeout stops at the response boundary, not at HTML parsing.
    return await run_in_sandbox_async(
        "app.utils.html_parsing", "page", value,
        timeout_seconds=5, memory_bytes=256 * 1024 * 1024,
        cpu_seconds=2, output_bytes=16 * 1024 * 1024,
    )
