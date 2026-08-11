"""canvas_rest.html — plain HTML text stripper (stdlib only, login-free).

Used to read Canvas submission bodies (which are HTML) into plain text while
preserving structure. Why structure matters: when a body contains an HTML table
(truth table, trace table, structured answer), flattening to bare text merges
all cells and you can no longer tell which value is in which row/column. So:

- table cells (<td>/<th>) -> joined with ' | '  -> `col1 | col2 | col3`
- row / block / line tags (<tr> <p> <div> <li> <h1..4> <br>) -> newline

Pure function, no network, no deps (Python stdlib `html.parser`).
"""
import re
from html.parser import HTMLParser

_CELL_END = {"td", "th"}                                   # -> ' | '
_LINE_END = {"tr", "p", "div", "li", "h1", "h2", "h3", "h4", "table"}  # -> newline


class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "br":                                    # void tag -> newline
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _CELL_END:
            self.parts.append(" | ")
        elif tag in _LINE_END:
            self.parts.append("\n")


def strip(html_text):
    """Return the text of an HTML string, tags removed, preserving table columns
    (`col1 | col2`) and line breaks."""
    if not html_text:
        return ""
    p = _Stripper()
    p.feed(html_text)
    text = "".join(p.parts)
    # tidy: drop the trailing ' | ' at a row end, collapse blank lines / runs of spaces
    text = re.sub(r"\s*\|\s*\n", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
