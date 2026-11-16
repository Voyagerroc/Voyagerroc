import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

from scripts.check_profile import external_status, extract_links, main, validate_readme


class ProfileChecks(unittest.TestCase):
    def fixture(self, readme, assets=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "README.md").write_text(readme, encoding="utf-8")
        for path, content in (assets or {}).items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return root

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
        root = self.fixture('[Remote](https://example.com)')
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


if __name__ == "__main__":
    unittest.main()
