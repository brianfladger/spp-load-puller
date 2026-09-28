"""
SPP hourly load puller — a small Streamlit app for the Wholesale Cost Allocation Study tool.

What it does
  1. You click the years you want.
  2. It asks portal.spp.org what is posted for each year and downloads it:
     the annual zip when SPP has posted one, otherwise the monthly files plus daily files for any month
     not yet covered. (Same approach as the CP-vs-NCP tracker app.)
  3. It reads both of SPP's file layouts (the wide one used through March 2026 and the long one since),
     converts SPP's GMT hour-ending timestamps to Central hour-beginning, and gives you a CSV.

Deploy: push app.py + requirements.txt to a GitHub repo, then "New app" at https://share.streamlit.io.
"""
import io
import re
import zipfile
from datetime import date

import pandas as pd
import requests
import streamlit as st

API = "https://portal.spp.org/file-browser-api"
TZ = "America/Chicago"
MONTHLY_RE = re.compile(r"^HOURLY_LOAD-(\d{6})\.csv$")
DAILY_RE = re.compile(r"^DAILY_HOURLY_LOAD-(\d{6})(\d{2})\.csv$")


# ----------------------------------------------------------------- SPP portal --
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def listing(year: int) -> list[str]:
    """Names of the files SPP has posted for a year."""
    r = requests.get(f"{API}/?fsName=hourly-load&path=/{year}&type=folder", timeout=60)
    r.raise_for_status()
    items = r.json()
    return [e["name"] for e in items] if isinstance(items, list) else []


@st.cache_data(ttl=24 * 3600, show_spinner=False, max_entries=2000)
def download(path: str) -> bytes | None:
    r = requests.get(f"{API}/download/hourly-load?path={path}", timeout=180)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.content


def plan_year(names: list[str], year: int) -> list[str]:
    """Which files to fetch: the zip if posted, otherwise monthly files plus daily files for uncovered months."""
    if f"{year}.zip" in names:
        return [f"{year}.zip"]
    monthly = sorted(n for n in names if MONTHLY_RE.match(n))
    covered = {MONTHLY_RE.match(n).group(1) for n in monthly}
    daily = sorted(n for n in names if DAILY_RE.match(n) and DAILY_RE.match(n).group(1) not in covered)
    return monthly + daily


# ----------------------------------------------------------------- parsing --
def parse_csv(raw: bytes) -> pd.DataFrame:
    """One SPP file -> long table: Zone, MarketHour (GMT, hour-ending, text), LoadMW."""
    df = pd.read_csv(io.BytesIO(raw))
    df = df.rename(columns=lambda c: str(c).strip()).dropna(how="all")
    if "Load MW" in df.columns:  # long layout (from 2026-03-24): CF and NC rows per zone per hour -> add them
        df = df.rename(columns={"Market Hour": "MarketHour", "Control Zone Name": "Zone", "Load MW": "LoadMW"})
        df["LoadMW"] = pd.to_numeric(df["LoadMW"], errors="coerce")
        out = df.groupby(["Zone", "MarketHour"], as_index=False)["LoadMW"].sum()
    else:  # wide layout: one column per zone
        out = df.melt(id_vars=["MarketHour"], var_name="Zone", value_name="LoadMW")
        out["LoadMW"] = pd.to_numeric(out["LoadMW"], errors="coerce")
    out["Zone"] = out["Zone"].astype(str).str.strip()
    return out.dropna(subset=["LoadMW"])


def to_central(long: pd.DataFrame) -> pd.DataFrame:
    """GMT hour-ending -> Central hour-beginning (naive local timestamps)."""
    hr = long["MarketHour"].astype(str).str.strip()
    hr = hr.where(hr.str.contains(":"), hr + " 00:00")  # a few old files drop "00:00" at midnight
    end_utc = pd.to_datetime(hr, utc=True, format="mixed", errors="coerce")
    long = long.assign(timestamp=(end_utc - pd.Timedelta(hours=1)).dt.tz_convert(TZ).dt.tz_localize(None))
    return long.dropna(subset=["timestamp"])[["timestamp", "Zone", "LoadMW"]]


def read_files(blobs: list[tuple[str, bytes]]) -> pd.DataFrame:
    frames = []
    for name, raw in blobs:
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                for member in z.namelist():
                    if member.lower().endswith(".csv"):
                        frames.append(parse_csv(z.read(member)))
        else:
            frames.append(parse_csv(raw))
    if not frames:
        return pd.DataFrame(columns=["timestamp", "Zone", "LoadMW"])
    long = to_central(pd.concat(frames, ignore_index=True))
    long = long.drop_duplicates(subset=["timestamp", "Zone"], keep="last")
    return long


def pull_year(year: int) -> tuple[pd.DataFrame, str]:
    """Not cached itself (it draws a progress bar); the network calls it makes are."""
    names = listing(year)
    files = plan_year(names, year)
    if not files:
        return pd.DataFrame(columns=["timestamp", "Zone", "LoadMW"]), "nothing posted yet"
    blobs, missing = [], 0
    bar = st.progress(0.0, f"{year}: starting…")
    for i, f in enumerate(files):
        bar.progress((i + 1) / len(files), f"{year}: {f} ({i + 1} of {len(files)})")
        raw = download(f"/{year}/{f}")
        if raw is None:
            missing += 1
        else:
            blobs.append((f, raw))
    bar.empty()
    how = "annual zip" if files[0].endswith(".zip") else (
        f"{sum(1 for f in files if MONTHLY_RE.match(f))} monthly + {sum(1 for f in files if DAILY_RE.match(f))} daily files")
    if missing:
        how += f" ({missing} missing)"
    return read_files(blobs), how


# ----------------------------------------------------------------- UI --
st.set_page_config(page_title="SPP load puller", page_icon="⚡", layout="centered")
st.title("SPP hourly load puller")
st.caption("Pulls NPPD's hourly load from portal.spp.org and gives you a CSV to drop into the cost allocation tool. "
           "Central time, hour-beginning.")

today = date.today()
years = list(range(today.year, 2010, -1))
default = [y for y in years if today.year - 3 <= y < today.year]
try:
    picked = st.pills("Years", years, selection_mode="multi", default=default)
except Exception:  # older Streamlit
    picked = st.multiselect("Years", years, default=default)
picked = sorted(picked or [])

if st.button("Pull from SPP", type="primary", disabled=not picked):
    frames, notes = [], []
    for y in picked:
        try:
            df, how = pull_year(y)
            frames.append(df)
            notes.append(f"{y}: {how}")
        except Exception as e:  # noqa: BLE001
            notes.append(f"{y}: failed — {e}")
    long = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["timestamp", "Zone", "LoadMW"])
    st.session_state["long"] = long
    st.session_state["notes"] = notes

if "long" not in st.session_state:
    st.info("Click the years you want, then Pull.")
    st.stop()

long = st.session_state["long"]
st.write(" · ".join(st.session_state["notes"]))
if long.empty:
    st.warning("No data came back.")
    st.stop()

wide = long.pivot_table(index="timestamp", columns="Zone", values="LoadMW", aggfunc="sum").sort_index()
zones = list(wide.columns)
zone = st.selectbox("Which zone is the system load?", zones, index=zones.index("NPPD") if "NPPD" in zones else 0)

per_year = wide[zone].groupby(wide.index.year).agg(["count", "max", "idxmax"])
per_year.columns = ["hours", "peak MW", "peak hour"]
st.dataframe(per_year.style.format({"peak MW": "{:,.0f}", "peak hour": lambda t: t.strftime("%Y-%m-%d %H:00")}),
             use_container_width=True)
st.line_chart(wide[zone].resample("D").max(), height=220)

tag = f"{min(picked)}-{max(picked)}" if len(picked) > 1 else str(picked[0])
tool_csv = wide[[zone]].rename(columns={zone: "system_mw"}).round(3)
tool_csv.index = tool_csv.index.strftime("%Y-%m-%d %H:00")
tool_csv.index.name = "timestamp"
c1, c2 = st.columns(2)
c1.download_button(f"Download {zone} load for the tool (CSV)", tool_csv.to_csv().encode(),
                   f"{zone.lower()}_system_load_{tag}.csv", "text/csv", type="primary", use_container_width=True)
all_csv = wide.round(3)
all_csv.index = all_csv.index.strftime("%Y-%m-%d %H:00")
all_csv.index.name = "timestamp"
c2.download_button("Download all zones (CSV)", all_csv.to_csv().encode(),
                   f"spp_all_zones_{tag}.csv", "text/csv", use_container_width=True)
st.caption("In the cost allocation tool: Step 1 → choose the downloaded file. It's already in Central hour-beginning time, "
           "so leave the time settings unticked.")
