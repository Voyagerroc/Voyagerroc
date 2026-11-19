import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

from scripts.check_profile import (
    MAX_IMAGE_BYTES,
    external_status,
    extract_images,
    extract_links,
    main,
    validate_profile,
    validate_readme,
)

ROOT = Path(__file__).resolve().parents[1]
PAGE = "[Türkçe](README.tr.md)\n"
PAGE_TR = "[English](README.md)\n"


class ProfileChecks(unittest.TestCase):
    def fixture(self, readme, assets=None, turkish=PAGE_TR, binary=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "README.md").write_text(readme, encoding="utf-8")
        if turkish is not None:
            (root / "README.tr.md").write_text(turkish, encoding="utf-8")
        for path, content in (assets or {}).items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        for path, size in (binary or {}).items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bytes(size))
        return root

    def issues(self, readme, **kwargs):
        return validate_profile(self.fixture(readme, **kwargs))[1]

    def test_missing_markdown_and_html_targets_show_source_locations(self):
        root = self.fixture('# Profile\n![Photo](missing.png)\n<img src="gone.svg">\n')
        _, issues = validate_readme(root)
        self.assertTrue(any("README.md:2: missing.png: missing local target" in x for x in issues))
        self.assertTrue(any("README.md:3: gone.svg: missing local target" in x for x in issues))

    def test_percent_encoded_paths_and_fragment_links_are_local(self):
        root = self.fixture('[Guide](docs/guide%20one.md#intro)\n[Top](#profile)',
                            {"docs/guide one.md": "# Intro\n"})
        self.assertEqual(validate_readme(root)[1], [])

    def test_parent_escape_is_rejected_even_when_the_target_exists(self):
        root = self.fixture('[Outside](../README.md)')
        self.assertIn("target leaves the repository", validate_readme(root)[1][0])

    def test_svg_must_parse_as_svg(self):
        root = self.fixture('<img src="banner.svg">', {"banner.svg": "<svg><broken>"})
        self.assertIn("invalid SVG", validate_readme(root)[1][0])
        (root / "banner.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        self.assertEqual(validate_readme(root)[1], [])

    def test_examples_are_ignored_but_nested_badge_destinations_are_checked(self):
        fence = chr(96) * 3
        links = extract_links(fence + '\n[Example](not-a-file)\n' + fence +
                              '\n[![CI](badge.svg)](https://example.com/ci)')
        self.assertEqual([(x.line, x.target) for x in links],
                         [(4, "badge.svg"), (4, "https://example.com/ci")])

    def test_default_run_never_opens_remote_urls(self):
        root = self.fixture("[Remote](https://example.com)\n" + PAGE)
        with mock.patch("scripts.check_profile.urlopen", side_effect=AssertionError("network disabled")):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root)]), 0)

    def test_missing_pages_differ_from_rate_limits_and_provider_errors(self):
        for status in [404, 410, 403, 429, 500, 503, 999]:
            def fail(request, timeout, code=status):
                raise HTTPError(request.full_url, code, "fixture", None, None)
            with self.subTest(status=status):
                state, detail = external_status("https://example.com", opener=fail)
                self.assertEqual(state, "missing" if status in {404, 410} else "unresolved")
                self.assertEqual(detail, f"HTTP {status}")

    def test_network_timeout_is_unresolved(self):
        def fail(request, timeout):
            raise URLError("synthetic timeout")
        self.assertEqual(external_status("https://example.com", opener=fail)[0], "unresolved")

    def test_successful_external_check_closes_response(self):
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        self.assertEqual(external_status("https://example.com", opener=lambda *a, **k: response),
                         ("ok", "HTTP 200"))
        response.__exit__.assert_called_once()

    # Guards added with the profile refresh: they protect the new two-language, image-based page.

    def test_both_language_pages_must_exist_and_link_to_each_other(self):
        self.assertTrue(any("cannot read README.tr.md" in x for x in self.issues(PAGE, turkish=None)))
        self.assertIn("README.md: does not link to README.tr.md", self.issues("# Profile\n"))
        self.assertIn("README.tr.md: does not link to README.md", self.issues(PAGE, turkish="# Profil\n"))
        self.assertEqual(self.issues(PAGE), [])

    def test_srcset_and_markdown_images_are_extracted_with_alt_text(self):
        text = ('<picture><source srcset="a-dark.webp 2x" media="(prefers-color-scheme: dark)">'
                '<img src="a.webp" alt="Alt"></picture>\n![Shot](b.png)\n<img src="c.png">')
        self.assertEqual([(x[1], x[2]) for x in extract_images(text)],
                         [("a-dark.webp", "(source)"), ("a.webp", "Alt"), ("c.png", None), ("b.png", "Shot")])
        self.assertIn("a-dark.webp", {x.target for x in extract_links(text)})

    def test_picture_sources_must_exist_locally(self):
        text = PAGE + '<picture><source srcset="assets/missing-dark.webp"><img src="assets/ok.webp" alt="A"></picture>'
        issues = self.issues(text, binary={"assets/ok.webp": 10})
        self.assertEqual(len(issues), 1)
        self.assertIn("assets/missing-dark.webp: missing local target", issues[0])

    def test_remote_images_are_rejected_in_html_and_markdown(self):
        for text in ('<img src="https://img.example.com/a.png" alt="A">', '![A](https://img.example.com/a.png)'):
            with self.subTest(text=text):
                self.assertTrue(any("not remote" in x for x in self.issues(PAGE + text)))

    def test_every_image_needs_alt_text(self):
        binary = {"a.png": 5}
        self.assertTrue(any("no alt attribute" in x for x in self.issues(PAGE + '<img src="a.png">', binary=binary)))
        self.assertTrue(any("empty alt" in x for x in self.issues(PAGE + '<img src="a.png" alt=" ">', binary=binary)))
        self.assertTrue(any("empty alt" in x for x in self.issues(PAGE + '![](a.png)', binary=binary)))
        self.assertEqual(self.issues(PAGE + '<img src="a.png" alt="Shot">', binary=binary), [])

    def test_no_email_address_or_mailto_in_pages_or_contributing(self):
        for text in (PAGE + "Write to someone@example.com", PAGE + "[Mail](mailto:someone@example.com)"):
            with self.subTest(text=text):
                self.assertTrue(any("e-mail address" in x for x in self.issues(text)))
        self.assertTrue(any("README.tr.md: contains an e-mail" in x for x in
                            self.issues(PAGE, turkish=PAGE_TR + "kisi@example.com")))
        root = self.fixture(PAGE)
        (root / "CONTRIBUTING.md").write_text("Mail someone@example.com\n", encoding="utf-8")
        self.assertTrue(any("CONTRIBUTING.md" in x for x in validate_profile(root)[1]))

    def test_image_budget_is_enforced_per_file_and_in_total(self):
        self.assertTrue(any("over the 350 KB" in x for x in
                            self.issues(PAGE, binary={"assets/big.webp": MAX_IMAGE_BYTES + 1})))
        many = {f"assets/i{n}.webp": 300 * 1024 for n in range(8)}
        self.assertTrue(any("in total" in x for x in self.issues(PAGE, binary=many)))
        self.assertEqual(self.issues(PAGE, binary={"assets/ok.webp": MAX_IMAGE_BYTES}), [])

    def test_light_and_dark_images_come_in_pairs(self):
        picture = ('<picture><source media="(prefers-color-scheme: dark)" srcset="assets/work-a-en-dark.webp">'
                   '<img src="assets/work-a-en-light.webp" alt="A"></picture>')
        binary = {"assets/work-a-en-dark.webp": 5, "assets/work-a-en-light.webp": 5}
        self.assertEqual(self.issues(PAGE + picture, binary=binary), [])
        lone = '<img src="assets/work-a-en-light.webp" alt="A">'
        self.assertTrue(any("without its twin" in x for x in self.issues(PAGE + lone, binary=binary)))

    def test_both_languages_must_show_the_same_images(self):
        def picture(slug, lang):
            return (f'<picture><source srcset="assets/{slug}-{lang}-dark.webp">'
                    f'<img src="assets/{slug}-{lang}-light.webp" alt="A"></picture>\n')
        binary = {f"assets/{s}-{l}-{t}.webp": 5 for s in ("work-a", "work-b") for l in ("en", "tr") for t in ("dark", "light")}
        same = self.issues(PAGE + picture("work-a", "en"), turkish=PAGE_TR + picture("work-a", "tr"), binary=binary)
        self.assertEqual(same, [])
        drift = self.issues(PAGE + picture("work-a", "en") + picture("work-b", "en"),
                            turkish=PAGE_TR + picture("work-a", "tr"), binary=binary)
        self.assertTrue(any("use different images: work-b" in x for x in drift))

    def test_the_real_profile_passes_every_guard(self):
        links, issues = validate_profile(ROOT)
        self.assertEqual(issues, [])
        self.assertGreater(len(links), 20)
        for name in ("README.md", "README.tr.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for stale in ("in review", "In review", "good first issue", "<table", "| ---"):
                self.assertNotIn(stale, text, f"{name} still contains {stale!r}")
        self.assertIn("Erol Tasci", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("Erol Taşcı", (ROOT / "README.tr.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
