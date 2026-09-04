"""
General-purpose graphing app.

Run with:
    pip install streamlit pandas plotly openpyxl --break-system-packages
    streamlit run graph_app.py
"""

import io
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Graphing App", page_icon=":material/analytics:", layout="wide")
st.title("Graphing app")

# ---------------------------------------------------------------------------
# 1. Data loading
# ---------------------------------------------------------------------------
uploaded_files = st.sidebar.file_uploader(
    "Upload one or more CSV/Excel files", type=["csv", "xlsx", "xls"],
    accept_multiple_files=True,
)

if not uploaded_files:
    st.info("Upload a CSV or Excel file from the sidebar to get started.")
    st.stop()


def _parse_likely_dates(frame: pd.DataFrame) -> pd.DataFrame:
    """CSV columns come back as plain strings even when they hold dates or
    times (unlike Excel, which pandas already parses to datetime64). Try
    parsing every text column, not just ones whose name hints at it — SCADA
    exports often label a time-of-day column with something generic (e.g.
    "Point Name" holding "03:00:00"), so a name-based filter misses real
    cases and leaves the X axis / cursor / range-filter treating time as a
    giant list of unrelated text categories."""
    for col in frame.columns:
        # pandas 3.0 reads CSV text as its own StringDtype ("str"), not the
        # legacy object dtype, so both need checking.
        if not (pd.api.types.is_object_dtype(frame[col]) or pd.api.types.is_string_dtype(frame[col])):
            continue
        # format="mixed" still infers per-element but skips the slower
        # dateutil fallback path (and its warning) pandas takes when it
        # can't guess one consistent format up front.
        parsed = pd.to_datetime(frame[col], format="mixed", errors="coerce")
        if parsed.notna().mean() >= 0.9:
            frame[col] = parsed
    return frame


@st.cache_data
def load_data(file) -> pd.DataFrame:
    name = file.name.lower()
    if name.endswith(".csv"):
        return _parse_likely_dates(pd.read_csv(file))
    # Excel usually parses date/time cells to datetime64 on its own, but a
    # column formatted as plain text in the sheet (or exported that way by
    # SCADA/historian software) comes through as text just like a CSV would.
    return _parse_likely_dates(pd.read_excel(file))


try:
    frames = [load_data(f) for f in uploaded_files]
except Exception as e:
    st.error(f"Could not read file: {e}")
    st.stop()

if len(frames) == 1:
    raw_df = frames[0]
else:
    # Multiple historian/SCADA exports for the same tags often arrive as
    # separate files covering different time windows — concatenate rows
    # rather than replacing, then sort by whichever column parsed as a
    # datetime so the combined series stays chronological regardless of
    # the order files were selected/dropped in.
    col_sets = {frozenset(f.columns) for f in frames}
    if len(col_sets) > 1:
        st.sidebar.warning(
            "Uploaded files don't all have the same columns — cells for a "
            "column missing from a given file will show blank for those rows."
        )
    raw_df = pd.concat(frames, ignore_index=True, sort=False)
    datetime_cols = raw_df.select_dtypes(include="datetime").columns
    if len(datetime_cols) > 0:
        raw_df = raw_df.sort_values(datetime_cols[0]).reset_index(drop=True)

st.sidebar.success(
    f"Loaded {raw_df.shape[0]} rows x {raw_df.shape[1]} columns"
    + (f" from {len(frames)} files" if len(frames) > 1 else "")
)

# Keep an editable copy in session state so renames/edits persist across
# reruns. Keyed on the set of uploaded filenames (not just one name) so
# adding/removing a file to the multi-file uploader is detected as a change.
source_key = tuple(sorted(f.name for f in uploaded_files))
if "df" not in st.session_state or st.session_state.get("_source_files") != source_key:
    st.session_state.df = raw_df.copy()
    st.session_state["_source_files"] = source_key

# ---------------------------------------------------------------------------
# Edit data: rename columns, edit values
# ---------------------------------------------------------------------------
with st.expander(
    "Edit data (rename columns / modify values)", expanded=False, icon=":material/edit:"
):
    st.caption("Rename columns")
    rename_cols = st.columns(min(4, len(st.session_state.df.columns)) or 1)
    new_names = {}
    for i, col in enumerate(st.session_state.df.columns):
        with rename_cols[i % len(rename_cols)]:
            new_names[col] = st.text_input(f"'{col}' ->", value=col, key=f"rename_{col}")

    if st.button("Apply renames", icon=":material/check:"):
        st.session_state.df = st.session_state.df.rename(columns=new_names)
        st.rerun()

    st.caption("Edit values (add/remove rows, edit cells)")
    edited_df = st.data_editor(st.session_state.df, num_rows="dynamic", key="editor")
    if st.button("Apply edits", icon=":material/check:"):
        st.session_state.df = edited_df
        st.rerun()

    edited_csv = st.session_state.df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download modified data as CSV",
        data=edited_csv,
        file_name="modified_data.csv",
        icon=":material/download:",
    )

df = st.session_state.df

with st.expander("Preview data", expanded=False, icon=":material/table_chart:"):
    st.dataframe(df.head(50))

numeric_cols = df.select_dtypes(include="number").columns.tolist()
datetime_cols = df.select_dtypes(include="datetime").columns.tolist()
all_cols = df.columns.tolist()


def guess_x_column(frame: pd.DataFrame) -> str:
    """Best-effort guess for the x-axis column: prefer datetime, then any
    column that looks like a date/time/index by name, else the first column."""
    if datetime_cols:
        return datetime_cols[0]
    name_hints = ("date", "time", "timestamp", "index", "id")
    for col in frame.columns:
        if any(hint in col.lower() for hint in name_hints):
            return col
    return frame.columns[0]


default_x = guess_x_column(df)

# ---------------------------------------------------------------------------
# 2. Chart configuration
# ---------------------------------------------------------------------------
st.sidebar.header("Chart settings")

chart_type = st.sidebar.selectbox(
    "Chart type",
    ["Line", "Scatter", "Bar", "Histogram", "Box", "Pie", "Heatmap"],
)

# Options common to line/scatter
supports_markers = chart_type in ("Line", "Scatter")
supports_multi_y = chart_type in ("Line", "Scatter", "Bar")

x_col = st.sidebar.selectbox(
    "X axis", all_cols, index=all_cols.index(default_x), help=f"Auto-detected: {default_x}"
)

if supports_multi_y:
    y_choices = [c for c in all_cols if c != x_col]
    y_cols = st.sidebar.multiselect(
        "Y axis (one or more series)",
        y_choices,
        default=([c for c in numeric_cols if c != x_col] or y_choices)[:3],
        help="Starts with just the first 3 to keep the chart readable — add more as needed.",
    )
elif chart_type == "Histogram":
    y_cols = [st.sidebar.selectbox("Value column", numeric_cols or all_cols)]
elif chart_type == "Box":
    y_cols = [st.sidebar.selectbox("Value column", numeric_cols or all_cols)]
elif chart_type == "Pie":
    y_cols = [st.sidebar.selectbox("Values column", numeric_cols or all_cols)]
else:
    y_cols = []

color_col = st.sidebar.selectbox(
    "Color / group by (optional)", ["(none)"] + all_cols
)
color_col = None if color_col == "(none)" else color_col

# Each Y series gets a fixed color so its trace and its own Y axis (ticks,
# axis line) are visually tied together. Skipped when grouping by color_col,
# since then a single Y column fans out into several differently-colored
# sub-traces and there's no one color left to match to the axis.
Y_PALETTE = [
    "#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e",
    "#17becf", "#e377c2", "#8c564b", "#7f7f7f", "#bcbd22",
]
y_color_map = {y: Y_PALETTE[i % len(Y_PALETTE)] for i, y in enumerate(y_cols)}

chart_title = st.sidebar.text_input("Chart title (optional)", value="")

mode = "lines"
if supports_markers:
    marker_choice = st.sidebar.segmented_control(
        "Style",
        ["Line only", "Markers only", "Line + markers"],
        default="Line + markers",
        required=True,
    )
    mode = {
        "Line only": "lines",
        "Markers only": "markers",
        "Line + markers": "lines+markers",
    }[marker_choice]

marker_symbol = "circle"
if supports_markers and "markers" in mode:
    marker_symbol = st.sidebar.selectbox(
        "Marker symbol",
        ["circle", "square", "diamond", "cross", "x", "triangle-up", "star", "hexagon"],
    )

log_y = st.sidebar.toggle("Log scale (Y)", value=False)
show_grid = st.sidebar.toggle("Show gridlines", value=True)
show_cursor = st.sidebar.toggle("Show cursor", value=True)

# ---------------------------------------------------------------------------
# Every plotted Y column gets its own Y axis/scale (see the "Wire up Y axes"
# section below) so trends of very different magnitude can share one plot
# without a manual per-series axis-picker.
# ---------------------------------------------------------------------------
y_axis_ids = {y: ("y" if i == 0 else f"y{i + 1}") for i, y in enumerate(y_cols)}
y_layout_keys = {y: ("yaxis" if i == 0 else f"yaxis{i + 1}") for i, y in enumerate(y_cols)}

# ---------------------------------------------------------------------------
# Hover behavior
# ---------------------------------------------------------------------------
st.sidebar.subheader("Hover behavior")
hover_choice = st.sidebar.selectbox(
    "Hover mode",
    [
        "Nearest point",
        "Compare all series at X (unified)",
        "Compare all series at X (separate labels)",
        "Compare all series at Y (unified)",
    ],
    index=2,
)
hovermode = {
    "Nearest point": "closest",
    "Compare all series at X (unified)": "x unified",
    "Compare all series at X (separate labels)": "x",
    "Compare all series at Y (unified)": "y unified",
}[hover_choice]
show_spikes = st.sidebar.toggle("Show crosshair guide lines on hover", value=False)

# ---------------------------------------------------------------------------
# Reference markers: formatted to match the data they point at
# ---------------------------------------------------------------------------
st.sidebar.subheader("Reference markers (optional)")
st.sidebar.caption(
    "X / Y: a single dashed line. X Range / Y Range: a shaded band between two values "
    "(e.g. a deadband) — put the low value in Value and the high value in Value 2. "
    "Point: labels the actual data point nearest Value (an X position) on Target "
    "column's line. Label is optional for all types — leave blank for an auto label. "
    "Color is optional too — leave it blank to use the type's default (red for X/X "
    "Range, green for Y/Y Range, the series' own color for Point)."
)

if "marker_table" not in st.session_state:
    st.session_state.marker_table = pd.DataFrame(
        {
            "type": pd.array([], dtype="string"),
            "target_column": pd.array([], dtype="string"),
            "value": pd.array([], dtype="string"),
            "value2": pd.array([], dtype="string"),
            "label": pd.array([], dtype="string"),
            "color": pd.array([], dtype="string"),
        }
    )

# Same principle as _sticky_range/_sticky_value below: st.session_state.marker_table
# is seeded once and never reassigned. A data_editor with key="marker_editor" already
# persists its own edits across reruns internally; feeding its edited output back in
# as next rerun's `data=` (an earlier version of this did) fights that internal diff
# tracking, so a freshly typed cell got reverted and needed to be entered twice before
# it stuck.
marker_table = st.sidebar.data_editor(
    st.session_state.marker_table,
    num_rows="dynamic",
    key="marker_editor",
    column_config={
        "type": st.column_config.SelectboxColumn(
            "Type", options=["X", "Y", "X Range", "Y Range", "Point"]
        ),
        "target_column": st.column_config.SelectboxColumn(
            "Target column", options=[x_col] + y_cols
        ),
        "value": st.column_config.TextColumn("Value"),
        "value2": st.column_config.TextColumn("Value 2 (range end)"),
        "label": st.column_config.TextColumn("Label (optional)"),
        "color": st.column_config.TextColumn(
            "Color (optional)", help="A CSS color name (e.g. orange) or hex code (e.g. #ff8800)"
        ),
    },
)
marker_table = marker_table.astype(
    {
        "type": "string",
        "target_column": "string",
        "value": "string",
        "value2": "string",
        "label": "string",
        "color": "string",
    }
)

# Label styling applies to every marker's text uniformly (font/background/
# position), separately from each row's own line/band color above — kept as
# one shared style rather than per-row columns so the table doesn't balloon
# with rarely-changed settings.
with st.sidebar.expander("Marker label style", expanded=False):
    label_font_color = st.color_picker("Font color", value="#000000")
    label_font_size = st.slider("Font size", min_value=8, max_value=32, value=12)
    style_cols = st.columns(2)
    label_bold = style_cols[0].checkbox("Bold", value=False)
    label_italic = style_cols[1].checkbox("Italic", value=False)
    label_bg_enabled = st.checkbox("Add label background", value=False)
    label_bg_color = (
        st.color_picker("Background color", value="#FFFFFF") if label_bg_enabled else None
    )
    label_position = st.selectbox(
        "Label position",
        ["Auto (per marker type)", "Top left", "Top right", "Bottom left", "Bottom right"],
    )


def _styled_label_text(text: str) -> str:
    """Wrap in Plotly's supported HTML-like tags — annotation text (unlike
    plain shape/axis text) renders a small tag subset including <b>/<i>."""
    if label_bold:
        text = f"<b>{text}</b>"
    if label_italic:
        text = f"<i>{text}</i>"
    return text


def _effective_position(default_position: str) -> str:
    """X/Y/Range markers all take a Plotly `annotation_position` keyword, but
    the valid set differs by orientation (vline/vrect accept top/bottom
    variants, hline/hrect accept left/right variants) — "top left", "top
    right", "bottom left", "bottom right" is the intersection valid for both,
    which is exactly the choice list offered above, so any selection can be
    passed straight through regardless of which of the four marker kinds it
    lands on."""
    if label_position == "Auto (per marker type)":
        return default_position
    return label_position.lower()


# Point markers use add_annotation's pixel arrow offset (ax/ay), not the
# annotation_position keyword the other four types use, so "position" maps to
# a direction to nudge the label away from the actual data point instead.
POINT_POSITION_OFFSETS = {
    "Auto (per marker type)": (0, -35),
    "Top left": (-40, -35),
    "Top right": (40, -35),
    "Bottom left": (-40, 35),
    "Bottom right": (40, 35),
}


def format_value_like(series: pd.Series, value: float) -> str:
    """Format a reference value using the same style as the series it refers to."""
    try:
        if pd.api.types.is_integer_dtype(series):
            return f"{int(round(value)):,}"
        maxabs = series.abs().max() if len(series) else abs(value)
        if maxabs >= 1000:
            return f"{value:,.2f}"
        if maxabs < 1:
            return f"{value:.4f}"
        return f"{value:,.2f}"
    except Exception:
        return str(value)


def format_datetime_like(series: pd.Series, value) -> str:
    """Format an x-marker value as a date/time string matching the data's granularity."""
    ts = pd.to_datetime(value)
    try:
        has_time_component = not (series.dt.hour == 0).all() or not (series.dt.minute == 0).all()
    except Exception:
        has_time_component = True
    return ts.strftime("%Y-%m-%d %H:%M:%S") if has_time_component else ts.strftime("%Y-%m-%d")


def _shape_safe(value):
    """Kaleido (used for PNG export) serializes shapes like add_vline/
    add_hline with a stricter JSON encoder than the rest of Plotly, and a
    bare pd.Timestamp trips it with "Type is not JSON serializable" — even
    though the exact same value inside trace data (a whole datetime64
    column) is fine. Converting to a plain python datetime sidesteps it."""
    return value.to_pydatetime() if isinstance(value, pd.Timestamp) else value


# ---------------------------------------------------------------------------
# Data window: lets the user narrow what's "currently shown" — this same
# subset drives the plot, the cursor readout, and the summary stats below.
# ---------------------------------------------------------------------------
def _sticky_range(key: str, lo, hi) -> None:
    """Seed/clamp a (lo, hi) tuple in session_state for a range slider.

    Passing value=(lo, hi) fresh on every rerun (as an earlier version did
    for every slider in this app, including the cursor ones below) fights
    the slider's own drag state — Streamlit re-applies that literal default
    on each rerun, so the handle looked stuck / snapped back instead of
    tracking a drag. Seeding session_state once via `key`, and never passing
    `value=` alongside it, is what lets the widget own its value afterwards.
    """
    current = st.session_state.get(key)
    if current is None or not (lo <= current[0] <= hi and lo <= current[1] <= hi):
        st.session_state[key] = (lo, hi)


def _sticky_value(key: str, lo, hi, default) -> None:
    """Same as _sticky_range but for a single-value slider."""
    current = st.session_state.get(key)
    if current is None or not (lo <= current <= hi):
        st.session_state[key] = default


def _infer_step(series: pd.Series):
    """Best-effort real sample interval for a slider's `step`.

    Without an explicit step, Streamlit defaults to something coarse for
    the value type — 1 day for a datetime slider, for instance — which for
    SCADA data sampled every second (say) meant the slider could only ever
    reach a couple of positions across a whole hour of data, looking like it
    "jumps" between a few fixed spots instead of moving smoothly. Using the
    data's own most common row-to-row gap as the step fixes that.
    """
    s = series.dropna().sort_values()
    if len(s) < 2:
        return None
    deltas = s.diff().dropna()
    positive = deltas[deltas > (pd.Timedelta(0) if pd.api.types.is_timedelta64_dtype(deltas) else 0)]
    if positive.empty:
        return None
    step = positive.mode().iloc[0]
    return step.to_pytimedelta() if isinstance(step, pd.Timedelta) else float(step)


view_df = df
supports_range = chart_type in ("Line", "Scatter", "Bar") and x_col in df.columns and len(df) > 1

if supports_range:
    # Lives in the main area (not the sidebar) since it's a primary control
    # for "what am I looking at", same as the cursor below it — the sidebar
    # is reserved for chart setup (columns, style, axes).
    st.subheader("Data window")
    if x_col in datetime_cols:
        min_x, max_x = df[x_col].min().to_pydatetime(), df[x_col].max().to_pydatetime()
        if min_x < max_x:
            range_key = f"range_{x_col}"
            _sticky_range(range_key, min_x, max_x)
            # Streamlit's default slider label for a datetime value is date-only
            # ("YYYY-MM-DD") — fine for data spanning weeks, useless for a few
            # hours of SCADA data where every handle looks like it's at the same
            # spot. format= must be passed explicitly to also show the time.
            sel_range = st.slider(
                "Show data between", min_value=min_x, max_value=max_x, key=range_key,
                step=_infer_step(df[x_col]), format="YYYY-MM-DD HH:mm:ss",
            )
            view_df = df[(df[x_col] >= sel_range[0]) & (df[x_col] <= sel_range[1])]
    elif x_col in numeric_cols:
        min_x, max_x = float(df[x_col].min()), float(df[x_col].max())
        if min_x < max_x:
            range_key = f"range_{x_col}"
            _sticky_range(range_key, min_x, max_x)
            sel_range = st.slider(
                "Show data between", min_value=min_x, max_value=max_x, key=range_key,
                step=_infer_step(df[x_col]),
            )
            view_df = df[(df[x_col] >= sel_range[0]) & (df[x_col] <= sel_range[1])]
    else:
        categories = df[x_col].dropna().unique().tolist()
        chosen = st.multiselect("Show categories", categories, default=categories)
        view_df = df[df[x_col].isin(chosen)] if chosen else df

if view_df.empty:
    st.warning("No data in the selected window.")
    st.stop()

# ---------------------------------------------------------------------------
# 3. Build figure
# ---------------------------------------------------------------------------
fig = None

if chart_type in ("Line", "Scatter"):
    fig = go.Figure()
    for y in y_cols:
        yaxis_ref = y_axis_ids[y]
        if color_col:
            for grp, sub in view_df.groupby(color_col):
                fig.add_trace(
                    go.Scatter(
                        x=sub[x_col], y=sub[y], mode=mode, name=f"{y} ({grp})",
                        marker=dict(symbol=marker_symbol), yaxis=yaxis_ref,
                    )
                )
        else:
            fig.add_trace(
                go.Scatter(
                    x=view_df[x_col], y=view_df[y], mode=mode, name=y,
                    marker=dict(symbol=marker_symbol, color=y_color_map[y]),
                    line=dict(color=y_color_map[y]),
                    yaxis=yaxis_ref,
                )
            )

elif chart_type == "Bar":
    fig = go.Figure()
    for y in y_cols:
        yaxis_ref = y_axis_ids[y]
        fig.add_trace(
            go.Bar(
                x=view_df[x_col], y=view_df[y], name=y, yaxis=yaxis_ref,
                marker_color=None if color_col else y_color_map[y],
            )
        )
    fig.update_layout(barmode="group")

elif chart_type == "Histogram":
    fig = px.histogram(view_df, x=y_cols[0], color=color_col)

elif chart_type == "Box":
    fig = px.box(view_df, x=color_col, y=y_cols[0])

elif chart_type == "Pie":
    fig = px.pie(view_df, names=x_col, values=y_cols[0])

elif chart_type == "Heatmap":
    corr = view_df[numeric_cols].corr()
    fig = go.Figure(
        data=go.Heatmap(z=corr.values, x=corr.columns, y=corr.columns, colorscale="RdBu")
    )

if fig is None:
    st.warning("Select at least one Y column to plot.")
    st.stop()

if log_y and chart_type not in ("Pie", "Heatmap"):
    fig.update_yaxes(type="log")

# ---------------------------------------------------------------------------
# Wire up one Y axis per plotted column (Line/Scatter/Bar), each colored to
# match its line. `anchor="free"` + `autoshift=True` is Plotly's own
# mechanism for stacking extra axes outward without overlapping — it works
# out the pixel offsets itself, which is far more robust than hand-computing
# paper-coordinate positions per axis.
# ---------------------------------------------------------------------------
def _make_axis(color: str | None, overlaying: bool, side: str, show_grid: bool) -> dict:
    style = dict(
        tickfont=dict(color=color) if color else {},
        showgrid=show_grid,
        side=side,
        automargin=True,
    )
    if overlaying:
        # Only axes that overlay the primary one need to be freed from the
        # normal x-anchored layout and pushed outward. The primary axis
        # (overlaying=False) stays anchored normally — giving IT anchor="free"
        # too (as an earlier version did) put it in a different Plotly
        # "shift group" than the overlay axes, so autoshift never knew to
        # keep the first same-side overlay axis clear of it, and they'd
        # render on top of each other.
        style.update(overlaying="y", anchor="free", autoshift=True)
    return style


if supports_multi_y and y_cols:
    sides = ["left", "right"]
    for i, y in enumerate(y_cols):
        color = None if color_col else y_color_map[y]
        style = _make_axis(color, overlaying=i > 0, side=sides[i % 2], show_grid=show_grid)
        fig.update_layout(**{y_layout_keys[y]: style})

def _parse_x_value(raw):
    """Parse a marker's Value/Value 2 field the same way the X column itself
    is typed — a date when X is a datetime column, else a plain float."""
    return pd.to_datetime(raw) if x_col in datetime_cols else float(raw)


def _clean(raw) -> str | None:
    """pd.isna() must run before any truthiness check on `raw` — a freshly
    added, not-yet-filled-in marker row's cells come through as pd.NA (the
    nullable "string" dtype's missing value), and `if raw` on a bare pd.NA
    raises "TypeError: boolean value of NA is ambiguous" before the isna()
    check ever gets a chance to short-circuit it."""
    if pd.isna(raw):
        return None
    return raw if raw else None


# ---------------------------------------------------------------------------
# Reference markers, formatted to match the data they point at. Five kinds:
# X / Y single dashed lines, X Range / Y Range shaded bands between two
# values (e.g. a frequency deadband), and Point which labels the actual data
# point nearest a given X on a chosen series' line.
# ---------------------------------------------------------------------------
if chart_type not in ("Pie", "Heatmap") and not marker_table.empty:
    for _, row in marker_table.iterrows():
        mtype = row.get("type")
        target = row.get("target_column")
        raw_value = row.get("value")
        raw_value2 = row.get("value2")
        custom_label = _clean(row.get("label"))
        row_color = _clean(row.get("color"))
        if pd.isna(mtype) or not mtype or pd.isna(raw_value) or raw_value in (None, ""):
            continue
        try:
            if mtype == "X":
                parsed = _parse_x_value(raw_value)
                label = custom_label or (
                    format_datetime_like(df[x_col], parsed)
                    if x_col in datetime_cols
                    else (format_value_like(df[x_col], parsed) if x_col in numeric_cols else str(parsed))
                )
                fig.add_vline(
                    x=_shape_safe(parsed), line_dash="dash", line_color=row_color or "red",
                    annotation_text=_styled_label_text(label),
                    annotation_position=_effective_position("top"),
                    annotation_font_color=label_font_color, annotation_font_size=label_font_size,
                    annotation_bgcolor=label_bg_color,
                )
            elif mtype == "Y":
                value = float(raw_value)
                ref_col = target if target in df.columns else (y_cols[0] if y_cols else None)
                label = custom_label or (
                    f"{ref_col}: {format_value_like(df[ref_col], value)}" if ref_col else str(value)
                )
                yaxis_ref = y_axis_ids.get(ref_col, "y")
                fig.add_hline(
                    y=value, line_dash="dash", line_color=row_color or "green",
                    annotation_text=_styled_label_text(label),
                    annotation_position=_effective_position("right"),
                    annotation_font_color=label_font_color, annotation_font_size=label_font_size,
                    annotation_bgcolor=label_bg_color,
                    yref=yaxis_ref,
                )
            elif mtype == "X Range":
                raw_value2 = _clean(raw_value2)
                if raw_value2 is None:
                    continue
                x0, x1 = sorted([_parse_x_value(raw_value), _parse_x_value(raw_value2)])
                fig.add_vrect(
                    x0=_shape_safe(x0), x1=_shape_safe(x1),
                    fillcolor=row_color or "red", opacity=0.1, line_width=0,
                    annotation_text=_styled_label_text(custom_label or "Range"),
                    annotation_position=_effective_position("top left"),
                    annotation_font_color=label_font_color, annotation_font_size=label_font_size,
                    annotation_bgcolor=label_bg_color,
                )
            elif mtype == "Y Range":
                raw_value2 = _clean(raw_value2)
                if raw_value2 is None:
                    continue
                y0, y1 = sorted([float(raw_value), float(raw_value2)])
                ref_col = target if target in df.columns else (y_cols[0] if y_cols else None)
                yaxis_ref = y_axis_ids.get(ref_col, "y")
                label = custom_label or (f"{ref_col} band" if ref_col else "Band")
                fig.add_hrect(
                    y0=y0, y1=y1, yref=yaxis_ref,
                    fillcolor=row_color or "green", opacity=0.12, line_width=0,
                    annotation_text=_styled_label_text(label),
                    annotation_position=_effective_position("right"),
                    annotation_font_color=label_font_color, annotation_font_size=label_font_size,
                    annotation_bgcolor=label_bg_color,
                )
            elif mtype == "Point":
                ref_col = target if target in y_cols else (y_cols[0] if y_cols else None)
                if not ref_col:
                    continue
                x_target = _parse_x_value(raw_value)
                if x_col in datetime_cols:
                    idx = (view_df[x_col] - pd.Timestamp(x_target)).abs().idxmin()
                else:
                    idx = (view_df[x_col] - x_target).abs().idxmin()
                point_row = view_df.loc[idx]
                actual_x, actual_y = point_row[x_col], point_row[ref_col]
                if pd.isna(actual_y):
                    continue
                label = custom_label or format_value_like(df[ref_col], actual_y)
                yaxis_ref = y_axis_ids.get(ref_col, "y")
                point_color = row_color or (y_color_map.get(ref_col, "black") if not color_col else "black")
                ax, ay = POINT_POSITION_OFFSETS.get(label_position, (0, -35))
                fig.add_annotation(
                    x=_shape_safe(actual_x), y=actual_y, yref=yaxis_ref,
                    text=_styled_label_text(label), showarrow=True, arrowhead=2, ax=ax, ay=ay,
                    font=dict(color=label_font_color, size=label_font_size),
                    bgcolor=label_bg_color if label_bg_enabled else "white",
                    bordercolor=point_color,
                )
                fig.add_trace(
                    go.Scatter(
                        x=[actual_x], y=[actual_y], yaxis=yaxis_ref, mode="markers",
                        marker=dict(size=10, color=point_color, line=dict(width=1, color="white")),
                        showlegend=False, hoverinfo="skip",
                    )
                )
        except (ValueError, TypeError, KeyError):
            continue

fig.update_layout(
    title=dict(text=chart_title or f"{chart_type} chart", x=0.5, xanchor="center"),
    xaxis_title=x_col if chart_type not in ("Pie", "Heatmap") else "",
    template="plotly_white",
    height=600,
    hovermode=hovermode if chart_type not in ("Pie", "Heatmap") else None,
    legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"),
    hoverlabel=dict(font=dict(size=13), namelength=-1),
)

if show_spikes and chart_type not in ("Pie", "Heatmap"):
    fig.update_xaxes(showspikes=True, spikemode="across", spikedash="dot", spikethickness=1)
    fig.update_yaxes(showspikes=True, spikemode="across", spikedash="dot", spikethickness=1)

if chart_type not in ("Pie", "Heatmap"):
    # Blanket pass covering chart types (Histogram, Box, single-axis Bar) that
    # skip the per-column _make_axis wiring above and so never got a showgrid
    # value at all; harmlessly reapplies the same value for the ones that did.
    fig.update_xaxes(showgrid=show_grid)
    fig.update_yaxes(showgrid=show_grid)

# ---------------------------------------------------------------------------
# Movable cursor: drag a slider along X and read off every trend's value
# at that point (snapped to the nearest actual row).
# ---------------------------------------------------------------------------
cursor_row = None
if show_cursor and chart_type in ("Line", "Scatter", "Bar") and y_cols and len(view_df) > 0:
    st.subheader("Cursor")
    if x_col in datetime_cols:
        min_x, max_x = view_df[x_col].min().to_pydatetime(), view_df[x_col].max().to_pydatetime()
        if min_x < max_x:
            cursor_key = f"cursor_{x_col}"
            _sticky_value(cursor_key, min_x, max_x, min_x)
            cursor_val = st.slider(
                "Position (X)", min_value=min_x, max_value=max_x, key=cursor_key,
                step=_infer_step(view_df[x_col]), format="YYYY-MM-DD HH:mm:ss",
            )
            idx = (view_df[x_col] - pd.Timestamp(cursor_val)).abs().idxmin()
            cursor_row = view_df.loc[idx]
    elif x_col in numeric_cols:
        min_x, max_x = float(view_df[x_col].min()), float(view_df[x_col].max())
        if min_x < max_x:
            cursor_key = f"cursor_{x_col}"
            _sticky_value(cursor_key, min_x, max_x, min_x)
            cursor_val = st.slider(
                "Position (X)", min_value=min_x, max_value=max_x, key=cursor_key,
                step=_infer_step(view_df[x_col]),
            )
            idx = (view_df[x_col] - cursor_val).abs().idxmin()
            cursor_row = view_df.loc[idx]
    else:
        options = view_df[x_col].astype(str).tolist()
        if options:
            cursor_cat_key = f"cursor_cat_{x_col}"
            if st.session_state.get(cursor_cat_key) not in options:
                st.session_state[cursor_cat_key] = options[0]
            chosen_x = st.select_slider("Position (X)", options=options, key=cursor_cat_key)
            match = view_df[view_df[x_col].astype(str) == chosen_x]
            if not match.empty:
                cursor_row = match.iloc[0]

    if cursor_row is not None:
        actual_x = cursor_row[x_col]
        if x_col in datetime_cols or x_col in numeric_cols:
            fig.add_vline(
                x=_shape_safe(actual_x), line_color="gray", line_width=1, line_dash="dot",
                annotation_text="cursor", annotation_position="top left",
            )
        else:
            st.caption(f"Cursor at: {actual_x}")

# ---------------------------------------------------------------------------
# One stats table for the data currently shown, with a "Current" column
# holding the cursor's reading when a cursor is active (blank otherwise —
# either "Show cursor" is off, or the chart type has no cursor at all, e.g.
# Histogram/Box/Pie/Heatmap). SCADA column names
# are often long ("SwYrd Frequency BUS 1 (Hz)"), so this stays a table with
# one row per series rather than tiles/metrics that would truncate them.
# Shown right below the cursor slider, above the plot, so the reading is the
# first thing you see after moving the cursor.
# ---------------------------------------------------------------------------
stats_df = None
if y_cols:
    numeric_y = [y for y in y_cols if pd.api.types.is_numeric_dtype(view_df[y])]
    if numeric_y:
        st.subheader("Stats for the data currently shown")
        current_vals = pd.Series(
            {y: (cursor_row[y] if cursor_row is not None else None) for y in numeric_y},
            name="Current",
        )
        stats_df = pd.DataFrame(
            {
                "Current": current_vals,
                "Min": view_df[numeric_y].min(),
                "Max": view_df[numeric_y].max(),
                "Mean": view_df[numeric_y].mean(),
                "Count": view_df[numeric_y].count(),
            }
        )
        stats_df.index.name = "Series"
        st.dataframe(stats_df, use_container_width=True)

st.plotly_chart(fig)


def _add_table_below(chart_png: bytes, table_df: pd.DataFrame, width: int) -> bytes:
    """Render table_df as its own small PNG (a Plotly Table, so the styling
    matches the chart) and stack it beneath the chart PNG into one image.
    Kaleido renders one figure at a time, so there's no way to bake a
    DataFrame into the chart's own image export directly — compositing two
    separate renders with Pillow is the straightforward way to get both in
    one file.
    """
    from PIL import Image

    display_df = table_df.reset_index()
    table_fig = go.Figure(
        data=[go.Table(
            header=dict(
                values=[f"<b>{c}</b>" for c in display_df.columns],
                fill_color="#f0f0f0", align="left", height=28,
            ),
            cells=dict(
                values=[display_df[c].tolist() for c in display_df.columns],
                align="left", height=26,
            ),
        )]
    )
    table_height = 40 + 30 * len(display_df)
    table_fig.update_layout(width=width, height=table_height, margin=dict(l=10, r=10, t=10, b=10))
    table_png = table_fig.to_image(format="png", scale=2)

    chart_img = Image.open(io.BytesIO(chart_png))
    table_img = Image.open(io.BytesIO(table_png))
    combined = Image.new(
        "RGB", (max(chart_img.width, table_img.width), chart_img.height + table_img.height), "white"
    )
    combined.paste(chart_img, (0, 0))
    combined.paste(table_img, ((combined.width - table_img.width) // 2, chart_img.height))
    buf = io.BytesIO()
    combined.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 4. Export
# ---------------------------------------------------------------------------
col1, col2 = st.columns(2)

with col1:
    html_buf = io.StringIO()
    fig.write_html(html_buf)
    st.download_button(
        "Download chart as HTML",
        data=html_buf.getvalue(),
        file_name="chart.html",
        mime="text/html",
        icon=":material/download:",
    )

with col2:
    include_stats_png = False
    if stats_df is not None:
        include_stats_png = st.checkbox("Include stats table in the PNG", value=False)
    try:
        png_bytes = fig.to_image(format="png", scale=2)
        if include_stats_png:
            png_bytes = _add_table_below(png_bytes, stats_df, width=fig.layout.width or 900)
        st.download_button(
            "Download chart as PNG",
            data=png_bytes,
            file_name="chart.png",
            mime="image/png",
            icon=":material/download:",
        )
    except Exception as e:
        st.caption(f"PNG export unavailable: {e}")
