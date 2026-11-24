import json
import logging
import os
import re
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from obd_codes.db import ensure_db, get_conn
from obd_codes.lookup import extract_codes, makes_payload, search
from obd_codes.sources import ATTRIBUTION

STATIC = Path(__file__).resolve().parent / "static"
PAGE = STATIC / "codes.html"
COST_NOTE = "Not priced in the fault-code sources"
logger = logging.getLogger(__name__)
_UK_REGISTRATION = re.compile(r"^[A-Z0-9]{1,8}$")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_db()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "").lower()


@app.get("/")
def root(request: Request):
    if _wants_html(request):
        return FileResponse(PAGE)
    count = get_conn().execute("SELECT count(*) FROM codes").fetchone()[0]
    return {
        "status": "DA PERFORMANCE backend running",
        "fault_codes": "/codes",
        "fault_code_search": "/api/codes?q=P0420",
        "fault_code_rows": count,
    }


@app.get("/codes")
def codes_page():
    return FileResponse(PAGE)


@app.get("/api/codes/makes")
def api_makes():
    return makes_payload()


@app.get("/api/codes")
def api_codes(q: str, make: str | None = None, limit: int = 30):
    if not q.strip():
        raise HTTPException(status_code=400, detail="Enter a code or a keyword.")
    return search(q, make=make or None, limit=max(1, min(limit, 50)))


@app.get("/api/codes/{code}")
def api_code(code: str, make: str | None = None):
    return search(code, make=make or None)


def _severity_bucket(text: str) -> str:
    lowered = (text or "").lower()
    if "serious" in lowered:
        return "high"
    if "caution" in lowered:
        return "medium"
    if "info" in lowered or "normally safe" in lowered:
        return "low"
    return "medium"


def _section(title: str, description: str, fix: str = "") -> dict:
    return {
        "title": title,
        "description": description,
        "likelihood": None,
        "fix": fix,
        "cost_guidance": COST_NOTE,
    }


def _reference_sources(entries: list[dict]) -> list[dict]:
    sources = [
        {
            "title": "OBD Codes List",
            "snippet": ATTRIBUTION["required_notice"],
            "url": "https://obdcodeslist.com/code-data.html",
            "type": "reference",
        }
    ]
    seen = {sources[0]["url"]}
    for entry in entries:
        for src in entry.get("sources") or []:
            url = src.get("url") or ""
            key = url or src.get("name")
            if not key or key in seen:
                continue
            seen.add(key)
            sources.append(
                {
                    "title": src.get("name") or "Source",
                    "snippet": src.get("licence") or "Fault-code source",
                    "url": url or None,
                    "type": "reference",
                }
            )
    return sources


def _causes_from_entry(entry: dict) -> list[dict]:
    fields = entry["fields"]
    fixes = fields["fixes"]["text"]
    fix_line = fixes or "No typical fix is recorded in the collected sources."
    items: list[dict] = []
    meaning = fields["meaning"]["text"]
    if meaning:
        items.append(_section("What it means", meaning))
    cause_lines = fields["causes"]["items"]
    if cause_lines:
        for line in cause_lines:
            items.append(_section(line[:160], line, fix_line))
    elif not entry["guidance_available"]:
        items.append(
            _section(
                entry["description"],
                "Meaning, causes, diagnosis, fixes and severity are not available from the collected sources for this entry.",
                "No typical fix is recorded in the collected sources.",
            )
        )
    else:
        items.append(_section(entry["description"], meaning or entry["description"], fix_line))
    for key, title in (
        ("symptoms", "Symptoms"),
        ("diagnosis", "Diagnosis steps"),
        ("fixes", "Typical fixes"),
        ("drive_advice", "Can I drive?"),
        ("severity", "Severity"),
    ):
        text = fields[key]["text"]
        if text:
            items.append(_section(title, text, fix_line if key == "fixes" else ""))
    return items


def _summarise_entry(entry: dict, vehicle_bit: str) -> str:
    fields = entry["fields"]
    meaning = fields["meaning"]["text"] or entry["description"]
    where = f" on the {vehicle_bit}" if vehicle_bit else ""
    summary = f"{entry['code']}{where}: {meaning}"
    drive = fields["drive_advice"]["text"]
    if drive:
        if not summary.endswith("."):
            summary += "."
        summary += " " + drive
    elif entry["letter"] == "B":
        summary += " Have a qualified mechanic check this airbag fault before relying on the restraint system."
    elif entry["letter"] == "C":
        summary += " Have a qualified mechanic check this braking or stability fault."
    if entry["original_language"]:
        summary += " The collected description is in the source's original language, not English."
    if entry["unverified_fields"] or entry.get("notes_unverified"):
        summary += " A source marked part of this guidance unverified."
    return summary


def diagnose_from_codes(codes: list[str], vehicle: dict) -> dict:
    make_name = str(vehicle.get("make") or "").strip()
    model = str(vehicle.get("model") or "").strip()
    vehicle_bit = " ".join(part for part in (make_name, model) if part)
    results = [search(code, make=make_name or None) for code in codes]
    primary = results[0]
    entries = primary["entries"]
    focus = next((entry for entry in entries if entry["relation"] == "selected"), None)
    if focus is None:
        focus = next((entry for entry in entries if entry["make"] == "GENERIC"), None)
    if focus is None and len(entries) == 1:
        focus = entries[0]

    if not entries:
        summary = primary["message"] or f"No entry for {primary['normalised_code']} in the fault-code database."
        if primary.get("hint"):
            summary = f"{summary} {primary['hint']}"
        causes = [
            _section(
                "Code not in the collected lists",
                summary,
                "Confirm the code and the vehicle make. Manufacturer codes differ by make.",
            )
        ]
        severity = "low"
    elif focus is None:
        summary = primary["warning"] or (
            f"{primary['normalised_code']} has more than one manufacturer definition."
        )
        if vehicle_bit:
            summary = f"For the {vehicle_bit}: {summary}"
        causes = [
            _section(f"{entry['code']} · {entry['make_label']}", entry["description"])
            for entry in entries
        ]
        severity = "medium"
    else:
        summary = _summarise_entry(focus, vehicle_bit)
        if primary.get("make_missing"):
            summary = f"{primary['make_missing']} {summary}"
        causes = _causes_from_entry(focus)
        severity = _severity_bucket(focus["fields"]["severity"]["text"])

    if len(codes) > 1:
        summary += " Also mentioned: " + ", ".join(codes[1:]) + "."

    return {
        "summary": summary,
        "severity": severity,
        "estimated_cost_min": None,
        "estimated_cost_max": None,
        "likely_causes": causes,
        "sources": _reference_sources(entries),
        "fault_code": primary,
        "fault_codes": results,
    }


@app.post("/diagnose")
async def diagnose(data: dict):
    raw_problem = data.get("problem") or ""
    vehicle = data.get("vehicle") or {}
    if not isinstance(vehicle, dict):
        vehicle = {}
    codes = extract_codes(str(raw_problem), vehicle.get("make"))
    if codes:
        return diagnose_from_codes(codes, vehicle)

    problem = str(raw_problem).lower()
    make = vehicle.get("make") or "Unknown"
    model = vehicle.get("model") or ""

    # Flexible matching
    if any(x in problem for x in ["grind", "click", "cv", "full lock", "turning", "driveshaft"]):
        summary = f"On the {make} {model}, grinding or clicking on full lock is almost always a worn outer CV joint."
        causes = [
            {"title": "Worn outer CV joint", "description": "Classic noise under load on full lock. Boot often split.", "likelihood": 84, "fix": "Replace driveshaft or outer joint. Check the other side.", "cost_guidance": "£180–£380"},
            {"title": "Wheel bearing", "description": "Can sound similar; usually changes more with speed.", "likelihood": 16, "fix": "Check for play and replace hub if needed.", "cost_guidance": "£120–£250"}
        ]
        cost = (180, 380)
        severity = "medium"
    elif any(x in problem for x in ["start", "crank", "battery", "won't start", "no start"]):
        summary = f"Starting problems on the {make} {model} are most often battery, connections or starter."
        causes = [
            {"title": "Battery or poor connections", "description": "Slow crank or single click. Very common.", "likelihood": 52, "fix": "Load-test battery and clean terminals.", "cost_guidance": "£60–£190"},
            {"title": "Starter motor", "description": "Loud click or grinding but no turnover.", "likelihood": 28, "fix": "Test and replace starter.", "cost_guidance": "£150–£340"}
        ]
        cost = (40, 340)
        severity = "medium"
    elif any(x in problem for x in ["overheat", "hot", "temperature", "coolant"]):
        summary = f"Overheating on the {make} {model} is usually thermostat, water pump or fan related."
        causes = [
            {"title": "Thermostat stuck closed", "description": "Temperature rises quickly.", "likelihood": 45, "fix": "Replace thermostat.", "cost_guidance": "£80–£170"}
        ]
        cost = (80, 400)
        severity = "high"
    else:
        summary = f"On the {make} {model}, the symptoms described need further checks. Try adding more detail (when it happens, noises, lights)."
        causes = [
            {"title": "More detail needed", "description": "The description was too general for a strong match.", "likelihood": 40, "fix": "Add when it happens, any noises, warning lights or recent work.", "cost_guidance": "Varies"}
        ]
        cost = (50, 250)
        severity = "low"

    return {
        "summary": summary,
        "severity": severity,
        "estimated_cost_min": cost[0],
        "estimated_cost_max": cost[1],
        "likely_causes": causes,
        "sources": [
            {"title": f"{make} owner forums", "snippet": "Common real-world reports matching this symptom.", "type": "forum"},
            {"title": "Technical guides", "snippet": "Standard diagnostic steps.", "type": "forum"}
        ]
    }


def _normalise_registration(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    registration = re.sub(r"\s+", "", value).upper()
    if not _UK_REGISTRATION.fullmatch(registration):
        return None
    return registration


def _post_dvla(url: str, api_key: str, registration: str) -> tuple[int, str]:
    payload = json.dumps({"registrationNumber": registration}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            return response.status, raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        text = raw.decode("utf-8", errors="replace") if raw else ""
        return exc.code, text


def _vehicle_from_dvla(registration: str, vehicle: dict) -> dict:
    capacity = vehicle.get("engineCapacity")
    return {
        "registration": registration,
        "make": vehicle.get("make"),
        "model": vehicle.get("model"),
        "year": vehicle.get("yearOfManufacture"),
        "fuel": vehicle.get("fuelType"),
        "engineSize": None if capacity is None else f"{capacity}cc",
        "colour": vehicle.get("colour"),
    }


@app.post("/api/vehicle")
def api_vehicle(data: dict):
    registration = _normalise_registration(data.get("registration"))
    if registration is None:
        return JSONResponse(
            status_code=400,
            content={"error": "Please provide a valid UK registration."},
        )

    api_key = os.environ.get("DVLA_API_KEY")
    if not api_key:
        return JSONResponse(
            status_code=500,
            content={"error": "DVLA_API_KEY is not configured."},
        )

    url = os.environ.get(
        "DVLA_API_URL",
        "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles",
    )
    try:
        status, body = _post_dvla(url, api_key, registration)
    except Exception:
        logger.exception("DVLA vehicle lookup failed")
        return JSONResponse(
            status_code=500,
            content={"error": "Vehicle lookup failed. Please try again."},
        )

    if status == 404:
        return JSONResponse(status_code=404, content={"error": "Vehicle not found."})
    if status < 200 or status >= 300:
        logger.error("DVLA vehicle lookup failed status=%s body=%s", status, body)
        return JSONResponse(
            status_code=502,
            content={"error": "Vehicle lookup failed. Please try again."},
        )

    try:
        vehicle = json.loads(body) if body else {}
    except json.JSONDecodeError:
        logger.exception("DVLA vehicle lookup returned invalid JSON status=%s body=%s", status, body)
        return JSONResponse(
            status_code=500,
            content={"error": "Vehicle lookup failed. Please try again."},
        )
    if not isinstance(vehicle, dict):
        logger.error("DVLA vehicle lookup returned a non-object status=%s body=%s", status, body)
        return JSONResponse(
            status_code=500,
            content={"error": "Vehicle lookup failed. Please try again."},
        )
    return _vehicle_from_dvla(registration, vehicle)

