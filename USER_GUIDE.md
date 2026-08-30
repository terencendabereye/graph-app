# Graph App — User Guide

A tool for turning a data export (CSV or Excel — SCADA/historian exports work
fine) into an interactive chart: pick which columns to plot, scrub through
the data with a cursor, filter to a time window, mark thresholds, and save
the result as an image or an interactive HTML file. No installation, no
account, no internet connection needed.

## Getting started

1. Unzip `GraphApp.zip` anywhere (Desktop, a USB drive, a network share —
   anywhere you can double-click a file).
2. Open the extracted `graph_app` folder and double-click `graph_app.exe`.
3. **Keep the whole folder together.** `graph_app.exe` needs the
   `_internal` folder sitting right next to it — don't copy just the `.exe`
   file on its own, or it won't start.
4. A window opens after a few seconds. That's the whole app — nothing else
   to install, nothing to sign in to.

### "Windows protected your PC"

The app isn't signed with a certificate, so Windows SmartScreen may show a
blue warning screen the first time you run it. This is expected for an
internal tool, not a sign anything is wrong. Click **More info**, then
**Run anyway**.

## Loading your data

Use **Upload a CSV or Excel file** in the left sidebar. Once it loads, you'll
see how many rows/columns came in.

- **CSV or Excel (`.xlsx`/`.xls`)** both work.
- Any column that looks like a date or time — even if it's not *named*
  anything like "date" or "time" (SCADA exports often label a time column
  something generic) — is automatically detected, so it can drive the time
  slider and cursor properly.

### Editing data before you plot

Expand **Edit data** if you need to:
- **Rename columns** — type a new name next to any column and click
  *Apply renames*. Handy since SCADA exports often use long, cryptic
  point names that only make sense to the person who set up the tags.
- **Edit values / add or remove rows** — an editable table; click
  *Apply edits* to commit changes.
- **Download modified data as CSV** — save your edited/renamed version to
  reuse later without redoing the renames.

Expand **Preview data** to see the first 50 rows as a plain table.

## Setting up the chart

Everything here lives in the left sidebar.

- **Chart type** — Line, Scatter, Bar, Histogram, Box, Pie, or Heatmap.
- **X axis** — usually auto-picked to your date/time column.
- **Y axis (one or more series)** — pick which columns to plot. Only the
  first 3 are selected by default so the chart doesn't start out cluttered —
  add more from the dropdown as needed.
- **Color / group by (optional)** — split each series into separate
  colored lines by another column's value (e.g. by unit number or status).
- **Chart title (optional)** — shown centered above the plot.
- **Style** — Line only / Markers only / Line + markers, plus a marker
  shape picker when markers are on.
- **Log scale (Y)** — useful when one series spans several orders of
  magnitude.
- **Hover behavior** — how tooltips behave when you point at the chart, and
  whether crosshair guide lines follow your cursor.
- **Reference markers** — add your own threshold lines: a row with type
  **X** draws a vertical line at a given date/time or X value; type **Y**
  draws a horizontal line at a given value, labeled against whichever
  column you point it at.

Each plotted series gets **its own Y axis**, automatically colored to match
its line — so series with very different scales (say, a frequency in Hz next
to a power output in MW) can share one chart without one of them looking
flat.

## Reading the data: Data window, Cursor, and Stats

These three sit above the chart, in this order:

1. **Data window** — a two-handled slider (or a checklist, if your X column
   is text rather than numbers/dates) that narrows the chart to a specific
   range. Everything below — the cursor and the stats table — reflects only
   what's inside this window.
2. **Cursor** — drag this slider to scrub through the data. It snaps to the
   nearest real row and draws a thin dotted line on the chart at that exact
   spot.
3. **Stats table** — one row per plotted series, showing:
   - **Current** — the value at wherever the cursor is right now
   - **Min / Max / Mean / Count** — over whatever's currently in the Data
     window

## Exporting

Below the chart:

- **Download chart as HTML** — a self-contained interactive file. Opens in
  any browser, fully zoomable/pannable, no internet or app needed to view it
  later — good for sharing with someone who doesn't have this tool.
- **Download chart as PNG** — a static image, for reports, emails, or
  slides. Tick **Include stats table in the PNG** first if you want the
  Current/Min/Max/Mean/Count table baked into the image below the chart.

## Tips

- If a series looks flat compared to the others, it's probably just fine —
  each series has its own scale (matched to its axis color), so check that
  color's numbers on the left/right edge of the chart rather than comparing
  line heights directly.
- If the cursor or the time-range slider feels like it's "jumping" in big
  steps, that means the app couldn't tell how frequently your data is
  sampled — this usually only happens with very small or irregular data.
- Renames and edits only last for the current session unless you download
  the modified CSV — closing the app loses them.
