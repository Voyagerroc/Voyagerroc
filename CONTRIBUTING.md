# Maintaining this profile

Use Python 3.11+; no packages or account credentials are required.

```console
python scripts/check_profile.py
python -m unittest discover -s tests -v
```

The first command checks the two profile pages, `README.md` and `README.tr.md`, offline:

- both pages exist and link to each other;
- every relative link and image target exists, and linked SVG files parse;
- images are files in `assets/`, never remote, and every image has alt text;
- no e-mail address appears in the pages or in this file;
- every light image has its dark twin, and both pages use the same set of images;
- every image stays under 350 KB and `assets/` stays under 2.2 MB.

Missing targets include the source line in the error. The check does not verify claims, remote availability or current PR status; review those separately.

Optional, network-dependent verification:

```console
python scripts/check_profile.py --check-external
```

HTTP 404/410 means a missing public destination and fails the check. HTTP 403/429/999, server errors and network failures are reported as unresolved; retry or verify them manually rather than declaring the page missing. External checks are deliberately excluded from CI to avoid failing on transient provider restrictions.

For contact, use the contact page of the website: <https://voyagerroctechnologies.com/en/legal/contact/>. Do not add e-mail addresses, private repository links, credentials or personal data. Describe local demos, prototypes, public releases and upstream PR states accurately, and list only upstream pull requests that are merged.

The images in `assets/` are rendered text and real captures, so no font files are stored here. Every image exists in a light and a dark version and in English and Turkish; keep both language pages in step when one changes.

The image sources are not in this repository: the owner renders the 20 images locally (HTML laid out in Chrome through Playwright, 2x PNG, then WebP) from real captures, and only the finished files are committed. A version, a status label or a sentence inside an image can therefore only change by re-rendering it. When one changes, re-render the affected images, then update the matching Markdown line and alt text in both language files in the same pull request. The check guards the structure (pairs, both languages, budgets), not the facts in the images.

The [profile checks workflow](.github/workflows/profile.yml) runs the offline validation and regression fixtures on Ubuntu and Windows. Dependencies are limited to Python's standard library; Dependabot monitors the pinned GitHub Actions. The required status checks are named `Offline profile / ubuntu-latest` and `Offline profile / windows-latest`: do not rename the workflow or its jobs.
