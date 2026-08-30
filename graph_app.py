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
uploaded_file = st.sidebar.file_uploader(
    "Upload a CSV or Excel file", type=["csv", "xlsx", "xls"]
)

if uploaded_file is None:
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
    raw_df = load_data(uploaded_file)
except Exception as e:
    st.error(f"Could not read file: {e}")
    st.stop()

st.sidebar.success(f"Loaded {raw_df.shape[0]} rows x {raw_df.shape[1]} columns")

# Keep an editable copy in session state so renames/edits persist across reruns
if "df" not in st.session_state or st.session_state.get("_source_file") != uploaded_file.name:
    st.session_state.df = raw_df.copy()
    st.session_state["_source_file"] = uploaded_file.name

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
    "Add vertical (X) or horizontal (Y) marker lines. X markers are read using the "
    "X column's type (dates parsed as dates). Y markers are tied to a specific series "
    "and labeled using that series' own formatting."
)

if "marker_table" not in st.session_state:
    st.session_state.marker_table = pd.DataFrame(
        {
            "type": pd.array([], dtype="string"),
            "target_column": pd.array([], dtype="string"),
            "value": pd.array([], dtype="string"),
        }
    )

marker_table = st.sidebar.data_editor(
    st.session_state.marker_table,
    num_rows="dynamic",
    key="marker_editor",
    column_config={
        "type": st.column_config.SelectboxColumn("Type", options=["X", "Y"]),
        "target_column": st.column_config.SelectboxColumn(
            "Target column", options=[x_col] + y_cols
        ),
        "value": st.column_config.TextColumn("Value"),
    },
)
st.session_state.marker_table = marker_table.astype(
    {"type": "string", "target_column": "string", "value": "string"}
)


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
            sel_range = st.slider(
                "Show data between", min_value=min_x, max_value=max_x, key=range_key,
                step=_infer_step(df[x_col]),
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
def _make_axis(color: str | None, overlaying: bool, side: str) -> dict:
    style = dict(
        tickfont=dict(color=color) if color else {},
        showgrid=False,
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
        style = _make_axis(color, overlaying=i > 0, side=sides[i % 2])
        fig.update_layout(**{y_layout_keys[y]: style})

# ---------------------------------------------------------------------------
# Reference markers, formatted to match the data they point at
# ---------------------------------------------------------------------------
if chart_type not in ("Pie", "Heatmap") and not marker_table.empty:
    for _, row in marker_table.iterrows():
        mtype = row.get("type")
        target = row.get("target_column")
        raw_value = row.get("value")
        if not mtype or pd.isna(raw_value) or raw_value in (None, ""):
            continue
        try:
            if mtype == "X":
                if x_col in datetime_cols:
                    parsed = pd.to_datetime(raw_value)
                    label = format_datetime_like(df[x_col], parsed)
                else:
                    parsed = float(raw_value)
                    label = format_value_like(df[x_col], parsed) if x_col in numeric_cols else str(parsed)
                fig.add_vline(
                    x=_shape_safe(parsed), line_dash="dash", line_color="red",
                    annotation_text=label, annotation_position="top",
                )
            elif mtype == "Y":
                value = float(raw_value)
                ref_col = target if target in df.columns else (y_cols[0] if y_cols else None)
                label = format_value_like(df[ref_col], value) if ref_col else str(value)
                yaxis_ref = y_axis_ids.get(ref_col, "y")
                fig.add_hline(
                    y=value, line_dash="dash", line_color="green",
                    annotation_text=f"{ref_col}: {label}" if ref_col else label,
                    annotation_position="right",
                    yref=yaxis_ref,
                )
        except (ValueError, TypeError):
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

# ---------------------------------------------------------------------------
# Movable cursor: drag a slider along X and read off every trend's value
# at that point (snapped to the nearest actual row).
# ---------------------------------------------------------------------------
cursor_row = None
if chart_type in ("Line", "Scatter", "Bar") and y_cols and len(view_df) > 0:
    st.subheader("Cursor")
    if x_col in datetime_cols:
        min_x, max_x = view_df[x_col].min().to_pydatetime(), view_df[x_col].max().to_pydatetime()
        if min_x < max_x:
            cursor_key = f"cursor_{x_col}"
            _sticky_value(cursor_key, min_x, max_x, min_x)
            cursor_val = st.slider(
                "Position (X)", min_value=min_x, max_value=max_x, key=cursor_key,
                step=_infer_step(view_df[x_col]),
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
# holding the cursor's reading when a cursor is active (blank otherwise, e.g.
# for Histogram/Box/Pie/Heatmap, which have no cursor). SCADA column names
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
