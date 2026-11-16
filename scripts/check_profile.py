"""Check profile links and SVG assets with the Python standard library."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class Link:
    line: int
    target: str


class HTMLLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in {"href", "src"} and value:
                self.links.append(Link(self.getpos()[0], value))


def extract_links(text):
    # Blank fenced examples while preserving source line numbers.
    visible = []
    fence = None
    for line in text.splitlines(keepends=True):
        match = re.match(r"^\s*([`~]{3,})", line)
        if match:
            marker = match.group(1)[0]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            visible.append("\n")
        else:
            visible.append("\n" if fence else line)
    text = "".join(visible)
    parser = HTMLLinks()
    parser.feed(text)
    links = list(parser.links)
    for number, line in enumerate(text.splitlines(), 1):
        # Matches Markdown destinations, including nested image badges.
        for match in re.finditer(r'\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+"[^"]*")?\s*\)', line):
            links.append(Link(number, match.group(1) or match.group(2)))
    return sorted(set(links), key=lambda item: (item.line, item.target))


def validate_readme(root):
    root = Path(root).resolve()
    try:
        links = extract_links((root / "README.md").read_text(encoding="utf-8"))
    except OSError as error:
        return [], [f"README.md:1: cannot read README: {error.strerror}"]
    issues = []
    for link in links:
        prefix = f"README.md:{link.line}: {link.target}"
        try:
            parsed = urlsplit(link.target)
            if parsed.scheme in {"http", "https"}:
                if not parsed.hostname:
                    issues.append(f"{prefix}: missing hostname")
                continue
            if parsed.scheme == "mailto":
                continue
            if parsed.scheme or parsed.netloc:
                issues.append(f"{prefix}: unsupported link scheme")
                continue
            if not parsed.path:
                continue
            target = (root / unquote(parsed.path).lstrip("/")).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                issues.append(f"{prefix}: target leaves the repository")
                continue
            if not target.is_file():
                issues.append(f"{prefix}: missing local target")
            elif target.suffix.lower() == ".svg":
                try:
                    element = ET.parse(target).getroot()
                    if element.tag.rsplit("}", 1)[-1] != "svg":
                        raise ValueError("root element is not svg")
                except (ET.ParseError, ValueError) as error:
                    issues.append(f"{prefix}: invalid SVG: {error}")
        except (ValueError, OSError) as error:
            issues.append(f"{prefix}: invalid target: {error}")
    return links, issues


def external_status(url, opener=None):
    """Only 404/410 establish a missing public destination."""
    if opener is None:
        opener = urlopen
    try:
        request = Request(url, headers={"User-Agent": "Voyagerroc-profile-check/1.0"})
        with opener(request, timeout=10) as response:
            code = response.status
    except HTTPError as error:
        code = error.code
        error.close()
    except (URLError, TimeoutError, OSError) as error:
        return "unresolved", type(error).__name__
    if 200 <= code < 400:
        return "ok", f"HTTP {code}"
    if code in {404, 410}:
        return "missing", f"HTTP {code}"
    return "unresolved", f"HTTP {code}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check-external", action="store_true", help="opt in to network checks")
    args = parser.parse_args(argv)
    links, issues = validate_readme(args.root)
    for issue in issues:
        print(issue)
    missing_external = 0
    if args.check_external:
        urls = sorted({link.target for link in links if urlsplit(link.target).scheme in {"http", "https"}})
        for url in urls:
            state, detail = external_status(url)
            print(f"External {state}: {url} ({detail})")
            missing_external += state == "missing"
    print(f"Profile: {len(links)} links inspected, {len(issues)} local issues, {missing_external} missing external pages.")
    return 1 if issues or missing_external else 0


if __name__ == "__main__":
    raise SystemExit(main())
