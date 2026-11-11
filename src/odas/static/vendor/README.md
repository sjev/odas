# Vendored front-end libraries

ODAS serves every script and stylesheet from its own origin. A jurist's office
may sit behind a restrictive proxy, and which case file someone reads is nobody
else's business. `tests/test_assets.py` fails the build if a template names a
third-party host again.

Nothing here is built or patched. Each file is byte-for-byte what the named
version publishes, so an upgrade is a re-download, not a merge.

| Path | Version | Source |
|------|---------|--------|
| `codemirror/codemirror.min.js` | 5.65.21 | `https://cdn.jsdelivr.net/npm/codemirror@5.65.21/lib/codemirror.min.js` |
| `codemirror/codemirror.min.css` | 5.65.21 | `https://cdn.jsdelivr.net/npm/codemirror@5.65.21/lib/codemirror.min.css` |
| `codemirror/yaml.js` | 5.65.21 | `https://cdn.jsdelivr.net/npm/codemirror@5.65.21/mode/yaml/yaml.js` |
| `leaflet/leaflet.js` | 1.9.4 | `https://unpkg.com/leaflet@1.9.4/dist/leaflet.js` |
| `leaflet/leaflet.css` | 1.9.4 | `https://unpkg.com/leaflet@1.9.4/dist/leaflet.css` |
| `leaflet/images/*` | 1.9.4 | `https://unpkg.com/leaflet@1.9.4/dist/images/` |

## Notes

**CodeMirror is loaded on one page only** — `zaak_bewerken.html`, for the raw
`index.md` editor behind the "Geavanceerd" toggle. That file is YAML, where
indentation carries meaning. Every other editor in ODAS is a plain `<textarea>`:
markdown reads fine as plain text, and a textarea keeps native spellcheck, undo
and find-in-page, which the component takes away. Only the `yaml` mode is
vendored; there is no markdown mode here because nothing asks for one.

**`leaflet/images/` is not optional.** `leaflet.css` refers to
`images/marker-icon.png`, `images/layers.png` and `images/layers-2x.png` by
relative path. Drop the directory and the map renders with blank markers.

**Map tiles still come from `tile.openstreetmap.org`** (`map_view.js`,
`map_picker.js`). Tiles are the map, and they load only when a latlon field
renders. This is the one accepted remote call, named in `test_assets.py` so it
stays deliberate.
