# Maintaining this profile

Use Python 3.11+; no packages or account credentials are required.

```console
python scripts/check_profile.py
python -m unittest discover -s tests -v
```

The first command checks relative README links, image targets and linked SVG syntax offline. Missing targets include the source line in the error. It does not verify claims, remote availability or current PR status; review those separately.

Optional, network-dependent verification:

```console
python scripts/check_profile.py --check-external
```

HTTP 404/410 means a missing public destination and fails the check. HTTP 403/429/999, server errors and network failures are reported as unresolved; retry or verify them manually rather than declaring the page missing. External checks are deliberately excluded from CI to avoid failing on transient provider restrictions.

Keep contact identity as **erol@voyagerroctechnologies.com**. Do not add private repository links, credentials or personal data. Describe local demos, prototypes, public releases and upstream PR states accurately.

The [profile checks workflow](.github/workflows/profile.yml) runs the offline validation and regression fixtures on Ubuntu and Windows. Dependencies are limited to Python's standard library; Dependabot monitors the pinned GitHub Actions.
