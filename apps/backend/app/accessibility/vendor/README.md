# Vendored axe-core

`axe.min.js` is axe-core 4.14.0 from npm (`npm pack axe-core@4.14.0`),
unmodified, under the Mozilla Public License 2.0 (`LICENSE`; bundled
dependencies in `LICENSE-3RD-PARTY.txt`). Source: https://github.com/dequelabs/axe-core

Verified when added (2026-10-29):
- tarball sha512 matched npm's `dist.integrity`
- `axe.min.js` sha256 `IMCf4Veoo0ow4kGqofza3mV3NPCKs3ns++t9RcxG6Hg=` matched axe-core's `sri-history.json`

To upgrade:
1. `npm pack axe-core@<version>` and check both hashes the same way.
2. Copy `axe.min.js` and the two licence files here.
3. Update `VERSION`.
4. Run `pytest tests/test_axe_vendor.py`.
