# DA PERFORMANCE Backend

FastAPI server the mobile app calls for diagnosis, plus a searchable OBD-II / EOBD fault-code database.

## Fault codes

About 84,700 codes (9,426 generic P/B/C/U codes and manufacturer codes for the major makes) are stored in a local SQLite file. The copy that ships in git is the gzipped CSV, `data/codes.csv.gz` (about 2 MB). The first startup builds `data/codes.db` with a full-text index. That file is about 45 MB and is not committed, and it is never sent to the browser: a search returns one code, or a short list of keyword matches.

Lookups follow the usual workshop habits:

- `PO420`, `p0420` and `P0 420` all resolve to `P0420`
- `audi`, `skoda`, `seat` and `vw` are the VW group; `vauxhall` also shows the related GM and Peugeot/Citroën lists
- a bare 5-digit code such as `00532` is the VAG / VCDS number `VAG00532`

Open the search page at `/codes` (or `/` in a browser). The phone app can keep calling `POST /diagnose`: a problem that contains a fault code is answered from this database, and any other description still uses the existing symptom matching.

```bash
curl 'http://localhost:8000/api/codes?q=P0420'
curl 'http://localhost:8000/api/codes?q=P1570&make=ford'
curl 'http://localhost:8000/api/codes?q=00532&make=vw'
curl 'http://localhost:8000/api/codes?q=misfire'
```

Each entry can include the meaning, likely causes, symptoms, diagnosis steps, fixes, severity, whether you can drive it, and the source link for that field. Manufacturer codes often only have a description, because that is all the public lists published. Where a source marks text unverified, the field is shown as unverified. Descriptions that are still in the source's original language are flagged in the notes.

Code data from OBD Codes List, https://obdcodeslist.com/code-data.html. Manufacturer and cross-check rows include autodiag2/database under the Open Database License (ODbL-1.0), Wal33D/dtc-database (MIT) and mytrile/obd-trouble-codes (MIT), plus OpenDTC, CarParts.com, python-OBD (GPL) and Automotive-9/dtc-codes. The search page lists each source.

## Quick free hosting (recommended: Render)

## Quick free hosting (recommended: Render)

1. Go to https://render.com and sign up (free).
2. Click **New +** → **Web Service**.
3. Connect a GitHub repo (or use “Public Git repository” / upload).
4. Or easiest: create a new GitHub repo, upload these two files (`main.py` and `requirements.txt`), then connect it on Render.
5. On Render set:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Deploy. Copy the URL Render gives you (e.g. `https://da-performance-xxxx.onrender.com`).
7. In the phone app HTML, find the line:
   `const LIVE_SEARCH_ENDPOINT = "..."`
   and change it to:
   `const LIVE_SEARCH_ENDPOINT = "https://your-render-url.onrender.com/diagnose";`

Once that is done the app will use the live backend automatically.

## Local test (if you ever have a computer)
```bash
pip install -r requirements-dev.txt
pytest
uvicorn main:app --reload
```
Then open http://localhost:8000/codes for fault codes, or http://localhost:8000/docs for the API.
