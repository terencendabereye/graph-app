# Graph App

A single-file Streamlit app that turns a CSV/Excel upload (SCADA/historian
exports in particular) into an interactive, multi-series Plotly chart — with
in-place data editing, one auto-colored Y axis per series, a time/value range
filter, a movable cursor with a live stats table, threshold markers, and
PNG/HTML export. Packaged as a self-contained Windows folder via PyInstaller
so it can be shared without requiring Python (or admin rights to install
anything) on the target machine.

**Just want to use the app?** See [USER_GUIDE.md](USER_GUIDE.md) instead —
this file is for building/developing it.

## Files

| File | Purpose |
|---|---|
| `graph_app.py` | The whole app. Single Streamlit script, run top-to-bottom on every interaction (Streamlit's normal execution model). |
| `launcher.py` | Entry point used only for the packaged app. Wraps `graph_app.py` in a native desktop window via `streamlit_desktop_app`, resolving the bundled script's path correctly whether run as a script or as a frozen PyInstaller binary. |
| `launcher.spec` | PyInstaller build spec, in **onedir** mode (a folder of files, not one giant exe — see "Building" below for why). Bundles `graph_app.py` as data, and uses `copy_metadata`/`collect_all` for Streamlit and its dependencies. |
| `find_metadata_deps.py` | Helper that checks which installed packages are actually present in the current venv, to keep `METADATA_PACKAGES` in `launcher.spec` accurate. Run it and copy its output list into the spec if you add new dependencies. |
| `build.ps1` | One-command Windows build script: installs missing build deps, runs `find_metadata_deps.py`, cleans `build/`+`dist/`, runs `pyinstaller launcher.spec`, then zips `dist\graph_app\` into `GraphApp.zip`. |

## Running in development

```bash
pip install streamlit pandas plotly openpyxl kaleido --break-system-packages
streamlit run graph_app.py
```

Opens in the browser at `localhost:8501`. No `--break-system-packages` flag needed
inside a venv.

## Building the distributable (Windows)

```powershell
pip install streamlit streamlit-desktop-app pyinstaller pandas plotly openpyxl kaleido
.\build.ps1
```

Output: `dist\graph_app\` (a folder — `graph_app.exe` plus an `_internal`
folder holding everything it needs) and `GraphApp.zip` at the project root.
**Ship the zip.** A recipient unzips it anywhere and runs `graph_app.exe`
inside the extracted folder — no install, no admin rights, no Python needed.

This is deliberately **onedir**, not a single onefile exe: `kaleido` (used
for PNG export) bundles a full headless Chromium, so a onefile build would
have to re-extract that whole payload to a temp folder on every launch —
slow, and more likely to trip antivirus heuristics that flag self-extracting
exes. Onedir keeps everything on disk and launches near-instantly. An
installer (Inno Setup, etc.) was considered and dropped: several target PCs
are company machines where installing anything requires admin permissions
that may not be available, so "unzip and run" is the safest default.

If a rebuild throws a new `importlib.metadata.PackageNotFoundError: <pkg>` for
a package not already covered, add `"<pkg>"` to `METADATA_PACKAGES` in
`launcher.spec` and re-run `.\build.ps1`. This happens because PyInstaller
strips package metadata (`.dist-info`) by default, but Streamlit and several
of its dependencies check their own installed version at import time via
`importlib.metadata` — `copy_metadata` restores just enough of that metadata
for the check to pass without bundling the full package again.

## App structure (`graph_app.py`)

The script runs top to bottom on every rerun:

1. **Data loading** — file upload (CSV/Excel, `accept_multiple_files=True`) →
   cached read per file → stored in `st.session_state.df` so edits persist
   across reruns without re-uploading. Multiple files are concatenated by
   row (not replaced) and, if any column parsed as a datetime, sorted by it —
   this is for SCADA/historian exports that arrive as several files covering
   different time windows for the same tags. Every text column (regardless
   of its name) is tried as a date/time during load — SCADA exports often
   label a time-of-day column with something generic (e.g. a column called
   "Point Name" holding `"03:00:00"`), so a name-based filter alone would
   miss real cases.
2. **Data editing** — an expander for renaming columns and editing/adding/
   deleting rows via `st.data_editor`. Writes back into `st.session_state.df`.
3. **Chart configuration** (sidebar) — chart type, X/Y column pickers
   (Y defaults to just the first 3 numeric columns, to avoid an overwhelming
   chart on first load), optional color/group-by, line style + marker
   symbol, chart title, hover mode, and the reference-marker table.
4. **Data window** (main area) — a range control that narrows `df` into
   `view_df`: a two-handled slider for numeric/datetime X, or a multiselect
   for categorical X. `view_df` is what actually gets plotted, cursor-
   scrubbed, and stats-summarized.
5. **Cursor** (main area) — a slider along X that snaps to the nearest actual
   row and drives the stats table's "Current" column plus a dotted line
   overlaid on the chart at that position.
6. **Stats table** (main area, above the plot) — one row per series: Current
   (at the cursor), Min, Max, Mean, Count, all over `view_df`.
7. **Figure + export** — builds the Plotly figure from `view_df`, wires up
   one Y axis per plotted column, overlays reference markers, renders the
   chart, and offers HTML/PNG downloads (PNG optionally with the stats table
   baked in below the chart).

### Key implementation details worth knowing before extending

- **One Y axis per series, not a manual axis picker**: every plotted column
  gets its own Y axis automatically, colored to match its line (skipped when
  grouping by "Color / group by", since a single column then fans out into
  several differently-colored sub-traces with no one color to match). Extra
  axes use Plotly's `anchor="free"` + `autoshift=True` so Plotly works out
  the outward offsets itself. The **primary** axis must stay a normal
  x-anchored axis (no `anchor="free"` on it) — giving it `anchor="free"` too
  puts it in a different Plotly "shift group" from the overlay axes, so
  `autoshift` doesn't know to keep the first same-side overlay axis clear of
  it, and they render on top of each other. This was a real, previously
  shipped bug — don't reintroduce it.
- **Sliders need `key` + session_state, never a literal `value=`**: every
  slider in this app (data window, cursor) seeds `st.session_state` once via
  `_sticky_range`/`_sticky_value` and is created with `key=` and no `value=`.
  Passing `value=` fresh on every rerun fights the widget's own drag state —
  it looks stuck/snapping back instead of tracking a drag.
- **Slider `step` is inferred from the data** via `_infer_step` (the most
  common row-to-row gap). Without it, Streamlit's default step for a
  datetime slider is 1 day, which for SCADA data sampled every second or so
  meant the slider could barely move across a whole hour of data.
- **PNG export and `pd.Timestamp`**: Kaleido (used for `fig.to_image`)
  serializes shapes like `add_vline`/`add_hline` with a stricter JSON
  encoder than the rest of Plotly, and throws `Type is not JSON
  serializable` on a bare `pd.Timestamp` scalar — even though the exact same
  type inside a trace's actual data (a whole datetime64 column) is fine.
  `_shape_safe()` converts to a plain `datetime` before it reaches either
  `add_vline` call. If you add another shape/annotation using a value pulled
  from a datetime column, run it through `_shape_safe()` too.
- **Reference markers** (`marker_table`) are stored as an explicitly
  string-typed 5-column DataFrame (`type`, `target_column`, `value`,
  `value2`, `label`). This is required, not optional — `st.data_editor`
  cross-checks each column's `column_config` type against the DataFrame's
  own inferred dtype, and an empty numeric-looking column configured as a
  `TextColumn` throws `StreamlitAPIException`. Keep new columns in this
  table string-typed and re-cast after every edit if you extend it.
  Five marker `type`s: `X`/`Y` (a single dashed line via `add_vline`/
  `add_hline`), `X Range`/`Y Range` (a shaded band between `value` and
  `value2` via `add_vrect`/`add_hrect` — e.g. a frequency deadband),
  and `Point` (labels the actual data row nearest `value` on
  `target_column`'s line — snaps to `view_df` the same way the cursor
  does, then draws a `go.Scatter` marker + `add_annotation` with an
  arrow at that row's real x/y, not the raw typed-in value).
  `label` is optional on every type; blank falls back to an
  auto-generated label from `format_value_like`/`format_datetime_like`.
- **Cursor line** (`add_vline`) is only drawn when X is numeric or datetime.
  Plotly's shape-annotation math for `add_vline`/`add_hline` breaks on
  categorical X axes (throws `TypeError: unsupported operand type(s) for
  +: 'int' and 'str'` trying to average two category labels) — for
  categorical X, the app shows the cursor value as a caption instead of a
  drawn line, via a `select_slider` over the distinct category strings.
- **"Include stats table in the PNG"** composites two separate Kaleido
  renders (the chart, and a `go.Table` built from the stats DataFrame) into
  one image with Pillow — there's no way to bake a DataFrame into a single
  figure's own image export directly.

## Known limitations / possible next steps

- No persistence between sessions beyond `st.session_state` — closing the
  app loses edits/config. Would need a proper save/load of the edited
  dataset + chart config as JSON if that's wanted.
- Reference markers of type "Y" pick their axis from which column they
  target, but silently fall back to the first Y column if `target_column`
  isn't currently plotted — worth a visible warning if this trips anyone up.
- The packaged app is unsigned, so Windows SmartScreen may flag
  `graph_app.exe` on first run ("Windows protected your PC" → "More info" →
  "Run anyway"). Expected; only worth fixing with a real code-signing
  certificate if distributing much more widely.
