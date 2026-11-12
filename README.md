# danzig666.github.io

GitHub Pages user site. It only forwards visitors:

- `/` goes to the QWebMap site, <https://danzig666.github.io/QWebMap/>.
- Old addresses under `/QGIS2VectorTiles/` (the repository's name before it was renamed to
  QWebMap) go to the same page under `/QWebMap/`, including deep links and embedded demo maps
  (`404.html`).

## `/QGIS/` – QGIS plugin catalogue

<https://danzig666.github.io/QGIS/> lists every public QGIS plugin in this account (any
non-archived repository with a plugin `metadata.txt`; forks are listed and marked as forks).
`scripts/build_qgis_page.py` generates `QGIS/index.html` and `QGIS/plugins.json` from the GitHub
API; the `Rebuild QGIS plugin page` workflow runs it daily, on demand, and when the script
changes, and commits only when the output changed. Set `EXCLUDE_REPOS` (comma-separated) in the
workflow to hide a repository.
