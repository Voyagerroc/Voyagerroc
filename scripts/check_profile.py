"""Check the profile pages, their links and their image assets with the Python standard library.

Offline guards: both language files exist and link to each other, relative links and image targets exist,
images are local files (no external image hosts), every image has alt text, no e-mail address appears in the
pages or in CONTRIBUTING.md, and the image files stay inside their size budget."""
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


PAGES = ("README.md", "README.tr.md")
MAX_IMAGE_BYTES = 350 * 1024
MAX_TOTAL_IMAGE_BYTES = 2200 * 1024
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


def srcset_targets(value):
    """URLs of a srcset value, without their width or density descriptors."""
    return [part.split()[0] for part in value.split(",") if part.strip()]


class HTMLLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.images = []  # (line, target, alt) for every <img>; alt is None when the attribute is missing

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        for name, value in attrs:
            if name in {"href", "src"} and value:
                self.links.append(Link(self.getpos()[0], value))
            elif name == "srcset" and value:
                for target in srcset_targets(value):
                    self.links.append(Link(self.getpos()[0], target))
        if tag == "img":
            self.images.append((self.getpos()[0], attributes.get("src") or "", attributes.get("alt")))
        elif tag == "source" and attributes.get("srcset"):
            for target in srcset_targets(attributes["srcset"]):
                self.images.append((self.getpos()[0], target, "(source)"))


def visible_text(text):
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
    return "".join(visible)


def extract_images(text):
    """(line, target, alt) for HTML <img>/<source> and Markdown images; alt is None when missing."""
    text = visible_text(text)
    parser = HTMLLinks()
    parser.feed(text)
    images = list(parser.images)
    for number, line in enumerate(text.splitlines(), 1):
        for match in re.finditer(r'!\[([^\]]*)\]\(\s*(?:<([^>]+)>|([^\s)]+))', line):
            images.append((number, match.group(2) or match.group(3), match.group(1)))
    return images


def extract_links(text):
    text = visible_text(text)
    parser = HTMLLinks()
    parser.feed(text)
    links = list(parser.links)
    for number, line in enumerate(text.splitlines(), 1):
        # Matches Markdown destinations, including nested image badges.
        for match in re.finditer(r'\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+"[^"]*")?\s*\)', line):
            links.append(Link(number, match.group(1) or match.group(2)))
    return sorted(set(links), key=lambda item: (item.line, item.target))


def validate_readme(root, name="README.md"):
    root = Path(root).resolve()
    try:
        links = extract_links((root / name).read_text(encoding="utf-8"))
    except OSError as error:
        return [], [f"{name}:1: cannot read {name}: {error.strerror}"]
    issues = []
    for link in links:
        prefix = f"{name}:{link.line}: {link.target}"
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


def is_remote(target):
    parsed = urlsplit(target)
    return bool(parsed.scheme or parsed.netloc)


def validate_profile(root):
    """Policy guards for the whole profile. Returns (links, issues) over every page."""
    root = Path(root).resolve()
    all_links, issues = [], []
    texts = {}
    for name in PAGES:
        links, found = validate_readme(root, name)
        all_links += links
        issues += found
        if not (root / name).is_file():
            continue
        text = (root / name).read_text(encoding="utf-8")
        texts[name] = text
        if "mailto:" in text or EMAIL.search(visible_text(text)):
            issues.append(f"{name}: contains an e-mail address; link the website contact page instead")
        for line, target, alt in extract_images(text):
            if is_remote(target):
                issues.append(f"{name}:{line}: {target}: images must be files in this repository, not remote")
            if alt is not None and not alt.strip():
                issues.append(f"{name}:{line}: {target}: image has empty alt text")
            elif alt is None:
                issues.append(f"{name}:{line}: {target}: image has no alt attribute")
    other = {"README.md": "README.tr.md", "README.tr.md": "README.md"}
    for name, partner in other.items():
        if name in texts and not any(link.target.split("#")[0] == partner for link in extract_links(texts[name])):
            issues.append(f"{name}: does not link to {partner}")
    contributing = root / "CONTRIBUTING.md"
    if contributing.is_file():
        text = contributing.read_text(encoding="utf-8")
        if "mailto:" in text or EMAIL.search(text):
            issues.append("CONTRIBUTING.md: contains an e-mail address; link the website contact page instead")
    total = 0
    assets = root / "assets"
    for image in sorted(assets.glob("*")) if assets.is_dir() else []:
        if image.suffix.lower() not in {".png", ".webp", ".jpg", ".jpeg", ".gif", ".svg"}:
            continue
        size = image.stat().st_size
        total += size
        if size > MAX_IMAGE_BYTES:
            issues.append(f"assets/{image.name}: {size // 1024} KB is over the {MAX_IMAGE_BYTES // 1024} KB image budget")
    if total > MAX_TOTAL_IMAGE_BYTES:
        issues.append(f"assets: {total // 1024} KB in total is over the {MAX_TOTAL_IMAGE_BYTES // 1024} KB budget")
    return all_links, issues


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
    links, issues = validate_profile(args.root)
    for issue in issues:
        print(issue)
    missing_external = 0
    if args.check_external:
        urls = sorted({link.target for link in links if urlsplit(link.target).scheme in {"http", "https"}})
        for url in urls:
            state, detail = external_status(url)
            print(f"External {state}: {url} ({detail})")
            missing_external += state == "missing"
    print(f"Profile: {len(PAGES)} pages, {len(links)} links inspected, {len(issues)} local issues, {missing_external} missing external pages.")
    return 1 if issues or missing_external else 0


if __name__ == "__main__":
    raise SystemExit(main())
