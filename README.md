# SPP load puller

Companion to the Wholesale Cost Allocation Study tool. Pulls NPPD's hourly load from portal.spp.org (public data) and hands back a CSV the tool reads directly. Holds no data, no keys, nothing private.

## Deploy on Streamlit Community Cloud (once, ~5 minutes)

1. **GitHub** — sign in at github.com → **New repository** → name it `spp-load-puller`, leave it Public → **Create repository**.
   On the new repo's page click **uploading an existing file**, drag in `app.py`, `requirements.txt`, `README.md` and the `.streamlit` folder → **Commit changes**.
2. **Streamlit** — sign in at share.streamlit.io (with GitHub) → **Create app** → *Deploy a public app from GitHub* → repository `spp-load-puller`, branch `main`, main file `app.py`.
   Under **App URL**, type a name such as `nppd-spp-puller` → **Deploy**. Two minutes later the app is live at `https://nppd-spp-puller.streamlit.app`.
3. **The tool** — open the cost allocation tool, Step 1 → "Puller address" → paste that address. Done.

## Use

Click the years → **Pull from SPP** → **Download NPPD load for the tool (CSV)** → choose that file in the tool's Step 1 file box.

## What it does with SPP's files

- Asks SPP's file listing what is posted for each year.
- Takes the annual zip if there is one (SPP posts it ~14 months after the year ends); otherwise the monthly `HOURLY_LOAD-YYYYMM.csv` files plus daily files for any month not yet covered.
- Reads both layouts: wide (one column per area, through March 2026) and long (since; CF + NC rows per area are added together).
- Converts GMT hour-ending timestamps to Central hour-beginning.
- Output: `timestamp, system_mw` (and an all-zones CSV if you want it).
