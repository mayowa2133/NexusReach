import DOMPurify from "dompurify";

// Force rel="noopener noreferrer" on any link that opens a new tab (audit L3),
// preventing reverse-tabnabbing where the opened page can rewrite window.opener.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (
    node.tagName === "A" &&
    node.getAttribute("target") === "_blank"
  ) {
    node.setAttribute("rel", "noopener noreferrer");
  }
});

const ALLOWED_TAGS = [
  "p", "br", "strong", "b", "em", "i", "u",
  "ul", "ol", "li",
  "h1", "h2", "h3", "h4", "h5", "h6",
  "a", "span", "div",
  "table", "thead", "tbody", "tr", "th", "td",
  "blockquote", "pre", "code", "hr", "sub", "sup",
];

const ALLOWED_ATTR = ["href", "target", "rel", "class"];

export function sanitizeHTML(dirty: string): string {
  return DOMPurify.sanitize(dirty, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ADD_ATTR: ["target"],
    FORBID_TAGS: ["script", "style", "iframe", "object", "embed", "form", "input"],
    FORBID_ATTR: ["onerror", "onclick", "onload", "onmouseover"],
  });
}
