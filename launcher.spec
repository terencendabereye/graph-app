# launcher.spec
# Build with:  pyinstaller launcher.spec
#
# Regenerate the METADATA_PACKAGES list by running find_metadata_deps.py
# in this same environment if you add/upgrade packages and hit a new
# "PackageNotFoundError" at runtime.

from PyInstaller.utils.hooks import copy_metadata, collect_all

METADATA_PACKAGES = [
    "streamlit",
    "pandas",
    "numpy",
    "click",
    "packaging",
    "altair",
    "pyarrow",
    "tornado",
    "cachetools",
    "protobuf",
    "pillow",
    "blinker",
    "gitpython",
    "pydeck",
    "tenacity",
    "toml",
    "typing_extensions",
    "requests",
    "urllib3",
    "watchdog",
    "rich",
    "plotly",
    "openpyxl",
    "kaleido",
    "narwhals",
]

datas = [("graph_app.py", ".")]
binaries = []
hiddenimports = []

for pkg in METADATA_PACKAGES:
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass  # package not installed / no metadata — skip quietly

# streamlit ships its compiled frontend assets inside the package; collect_all
# grabs those data files plus every submodule so nothing is missing at runtime.
for pkg in ("streamlit", "plotly", "kaleido"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

# onedir, not onefile: onefile would re-extract this whole payload (kaleido
# alone bundles a full headless Chromium) to a temp folder on every launch,
# which is slow and looks more "packer-like" to antivirus heuristics. onedir
# keeps everything on disk as a folder — still fully self-contained and still
# just one file to hand out once it's zipped up (see build.ps1), but launches
# near-instantly and there's no installer/admin rights involved either way.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="graph_app",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,  # keep True until it works reliably, then switch to False
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="graph_app",
)
