# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Streamlit app (`graph_app.py`) that turns an uploaded CSV/Excel file (SCADA/historian
exports in particular) into an interactive, multi-series Plotly chart, packaged as a self-contained
Windows folder via PyInstaller so it can run without Python installed on the target machine.

## Commands

Run in development:

```bash
pip install streamlit pandas plotly openpyxl kaleido --break-system-packages
streamlit run graph_app.py
```

Opens at `localhost:8501`. Drop `--break-system-packages` inside a venv.

Build the distributable (Windows only):

```powershell
pip install streamlit streamlit-desktop-app pyinstaller pandas plotly openpyxl kaleido
.\build.ps1
```

`build.ps1` installs missing build deps, runs `find_metadata_deps.py` (regenerates
`metadata_deps.txt`), wipes `build/`+`dist/`, runs `pyinstaller launcher.spec`, then zips the
result. Output is `dist\graph_app\` (a folder — `graph_app.exe` + an `_internal` folder) and
`GraphApp.zip` at the project root. **The zip is what gets shared** — unzip anywhere, run
`graph_app.exe` inside, no install/no admin rights needed.

This is **onedir**, not onefile, on purpose: `kaleido` (PNG export) bundles a full headless
Chromium, and onefile mode would re-extract that whole payload to a temp dir on every launch —
slow, and more likely to trip antivirus heuristics. An installer was also considered and rejected:
some target PCs are company machines where installing requires admin rights that may not be
available. Don't reintroduce either without being asked — this was a deliberate choice, not an
oversight.

There is no test suite or linter configured in this repo.

### If a rebuild throws `importlib.metadata.PackageNotFoundError: <pkg>`

PyInstaller strips `.dist-info` metadata by default, but Streamlit and several dependencies
check their own version via `importlib.metadata` at import time. Add `"<pkg>"` to
`METADATA_PACKAGES` in `launcher.spec` (and to `CANDIDATES` in `find_metadata_deps.py` if you
want it auto-detected going forward), then re-run `.\build.ps1`.

## Architecture

| File | Purpose |
|---|---|
| `graph_app.py` | The entire app. Single Streamlit script, re-run top-to-bottom on every UI interaction (Streamlit's normal execution model) — there is no separate backend. |
| `launcher.py` | Entry point used only by the packaged app. Wraps `graph_app.py` in a native desktop window via `streamlit_desktop_app`; resolves the bundled script's path via `sys._MEIPASS` when frozen. |
| `launcher.spec` | PyInstaller build spec, **onedir** mode (`EXE(..., exclude_binaries=True)` + `COLLECT(...)`, not a single-file `EXE`). Bundles `graph_app.py` as data and uses `copy_metadata`/`collect_all` for Streamlit + deps. |
| `find_metadata_deps.py` | Checks which candidate packages are actually installed in the active venv; writes `metadata_deps.txt` and prints the list to copy into `METADATA_PACKAGES`. |
| `build.ps1` | One-command Windows build: install → discover metadata deps → clean → `pyinstaller` → zip `dist\graph_app\` into `GraphApp.zip`. |

### `graph_app.py` execution phases (top to bottom, every rerun)

1. **Data loading** — file upload (`accept_multiple_files=True`) → each file's read is
   `@st.cache_data`-cached individually → stored in `st.session_state.df` so edits/renames persist
   across reruns without re-uploading. More than one file is `pd.concat`-ed by row (not
   replaced — the old single-file behavior overwrote the previous upload, which is exactly the
   bug this fixed) and, if any resulting column is a datetime dtype, sorted by the first one, so
   several historian exports covering different time windows for the same tags land in one
   chronological series regardless of upload order. Every text column (CSV *or* Excel) is run
   through `_parse_likely_dates`, which tries `pd.to_datetime` on it regardless of column name and
   keeps the conversion if ≥90% parses cleanly.
2. **Data editing** — expander for renaming columns and editing/adding/deleting rows via
   `st.data_editor`, written back into `st.session_state.df`.
3. **Chart configuration** (sidebar) — chart type, X/Y pickers (Y defaults to the first 3 numeric
   columns), color/group-by, line style + marker symbol, chart title, hover mode,
   reference-marker table.
4. **Data window** (main area, not sidebar) — a range control (two-handled slider for
   numeric/datetime X, multiselect for categorical X) that narrows `df` into `view_df`. `view_df`
   is the single source of truth for what's plotted, cursor-scrubbed, and stats-summarized.
5. **Cursor** (main area) — a slider that snaps to the nearest actual row in `view_df` and feeds
   both a dotted `add_vline` overlay on the chart and the stats table's "Current" column.
6. **Stats table** (main area, above the plot, right below the cursor slider) — one row per
   series: Current/Min/Max/Mean/Count.
7. **Figure build + export** — builds the Plotly figure from `view_df`, wires up one Y axis per
   plotted column, overlays reference markers, renders the chart, offers HTML/PNG export (PNG
   optionally with the stats table composited below it).

### Non-obvious implementation details to preserve when extending

- **One Y axis per plotted column, not a manual per-series axis picker.** Colored to match its
  line via `y_color_map` (skipped when "Color / group by" is set, since a column then fans out
  into several differently-colored sub-traces with no single color to match). Extra axes use
  `anchor="free"` + `autoshift=True` + `overlaying="y"` — Plotly works out the outward pixel
  offsets itself. **The primary axis must NOT also get `anchor="free"`** — an earlier version did
  this, which puts the primary axis in a different Plotly "shift group" from the overlay axes, so
  `autoshift` never learns to keep the first same-side overlay axis clear of it, and the two
  render on top of each other. See `_make_axis`.
- **Every slider uses `key=` + `st.session_state`, never a literal `value=`.** `_sticky_range` /
  `_sticky_value` seed a default into session_state once; the slider is then created with only
  `key=`. Passing `value=` fresh on every rerun (an earlier version did this for every slider in
  the app) fights the widget's own drag state and makes it look stuck / snap back instead of
  tracking a drag.
- **Slider `step` is inferred from the data** (`_infer_step`: the most common row-to-row gap in
  the column), not left to Streamlit's default. Streamlit defaults a datetime slider's step to 1
  day, which for SCADA data sampled every second or so meant the slider could only ever reach a
  couple of positions across an hour of data — looked like it was "jumping" instead of moving
  smoothly.
- **Both datetime sliders pass `format="YYYY-MM-DD HH:mm:ss"` explicitly.** Streamlit's own
  default label for a `datetime` slider is date-only, so a data window of a few hours showed the
  same date on both handles with no way to tell them apart. Numeric-X sliders don't take this
  format string (it's date-format syntax, meaningless for a plain float) — only the two
  `x_col in datetime_cols` branches (data-window range slider, cursor slider) need it.
- **`pd.Timestamp` scalars break Kaleido's PNG export** (`Type is not JSON serializable`) when
  passed to `add_vline`/`add_hline`, even though the same type inside a trace's actual array data
  is fine — Kaleido (PNG rendering) uses a stricter JSON encoder than the rest of Plotly for
  shapes specifically. `_shape_safe()` converts to a plain `datetime` first; both `add_vline` call
  sites (cursor line, X-type reference marker) go through it. Route any new datetime-valued
  shape/annotation through it too.
- **`st.session_state.marker_table` is seeded once and never reassigned** — same principle as
  `_sticky_range`/`_sticky_value` above, but for `data_editor` instead of `slider`. An earlier
  version fed the edited/cast output back into `st.session_state.marker_table`, which is what
  `data_editor(..., key="marker_editor")` reads as its `data=` argument on the next rerun; since
  `data_editor` already persists its own edits across reruns internally via that `key`, feeding
  its output back in fought that internal diff tracking — a freshly typed cell got reverted and
  had to be entered twice before it stuck. The `.astype(...)` cast for downstream use must be
  assigned to a local (`marker_table = marker_table.astype(...)`), not written back to session
  state.
- **`marker_table`** (reference markers) must stay an explicitly string-typed DataFrame (`type`,
  `target_column`, `value`, `value2`, `label`) — `st.data_editor`'s `column_config` type is
  cross-checked against the DataFrame's own inferred dtype, and an empty numeric-looking column
  configured as a `TextColumn` throws `StreamlitAPIException`. Re-cast to string after every edit
  if extended further. Five `type`s: `X`/`Y` single dashed lines, `X Range`/`Y Range` shaded bands
  (`add_vrect`/`add_hrect`) between `value` and `value2` — the deadband use case — and `Point`,
  which does **not** plot the typed-in value directly: it looks up the nearest row to `value` in
  `view_df` (same nearest-row snap as the cursor slider) and labels that row's actual x/y, so the
  label always matches a real sample. `label` is optional everywhere; blank uses the same
  `format_value_like`/`format_datetime_like` auto-formatting as `X`/`Y` markers.
- **Cursor line** (`add_vline`) is only drawn when X is numeric or datetime — Plotly's
  shape-annotation math breaks on categorical X (`TypeError` averaging two category labels). For
  categorical X the app uses a `select_slider` over the distinct category strings and shows the
  cursor value as a caption instead of a drawn line. Don't drop this guard without testing a Bar
  chart with a text X column.
- Reference markers of type "Y" pick their axis from which column they target (`y_axis_ids`), but
  silently fall back to the first Y column if `target_column` isn't currently plotted — a known
  sharp edge, not a bug to "fix" reflexively.
- **CSV/Excel date parsing**: `_parse_likely_dates` tries `pd.to_datetime(..., format="mixed")` on
  every object/string column, keeping the result if ≥90% parses non-null — it does **not** gate on
  the column name. An earlier version only tried columns whose name contained "date"/"time"/
  "timestamp", which missed real cases (a SCADA column literally named "Point Name" holding
  `"03:00:00"` strings) and left the entire datetime-aware path (range slider, cursor slider,
  `add_vline`, X-type reference markers) silently falling back to the categorical (text) code path
  instead. When checking a column's dtype here, test both `pd.api.types.is_object_dtype` and
  `is_string_dtype` — pandas 3.0's default CSV string dtype (`StringDtype`, printed as `str`) is
  not `object` dtype, so an `== object` check alone misses it.
- **"Include stats table in the PNG"** (`_add_table_below`) renders the stats DataFrame as its own
  `go.Table` figure, exports it to PNG separately via Kaleido, and stacks the two PNGs with
  Pillow — there's no single-figure way to bake a DataFrame into a chart's own image export.
