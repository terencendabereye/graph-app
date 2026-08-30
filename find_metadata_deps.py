"""
find_metadata_deps.py

Figures out which installed packages Streamlit (and friends) query via
importlib.metadata at import time, so PyInstaller knows which packages
need --copy-metadata. Run this in the SAME virtual environment you use
to build the .exe.

Usage:
    python find_metadata_deps.py

Prints a ready-to-use list of --copy-metadata flags, and also writes
metadata_deps.txt for the build script to read.
"""

import importlib.metadata as im

# Packages Streamlit (and its own dependency chain) commonly look up by
# version at import time. This list is a superset drawn from Streamlit's
# requirements plus known past PyInstaller error reports; harmless to
# include extras that happen not to be needed.
CANDIDATES = [
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

found = []
missing = []
for name in CANDIDATES:
    try:
        im.version(name)
        found.append(name)
    except im.PackageNotFoundError:
        missing.append(name)

print("Packages present in this environment (will add --copy-metadata for these):")
for name in found:
    print(f"  {name}")

if missing:
    print("\nNot installed / not found (skipped):")
    for name in missing:
        print(f"  {name}")

with open("metadata_deps.txt", "w") as f:
    f.write("\n".join(found))

flags = " ".join(f"--copy-metadata {name}" for name in found)
print("\nPyInstaller flags:\n")
print(flags)
