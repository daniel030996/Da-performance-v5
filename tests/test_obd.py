"""Fault-code lookup, API and the existing symptom diagnosis."""

from fastapi.testclient import TestClient

from obd_codes.db import COLUMNS, get_conn
from obd_codes.lookup import (
    extract_codes,
    make_group,
    normalise_code,
    search,
    serialise_entry,
)
from main import app

client = TestClient(app)


def test_normalise_letter_o_spaces_and_vag_digits():
    assert normalise_code("PO420") == "P0420"
    assert normalise_code("po420") == "P0420"
    assert normalise_code("P0 420") == "P0420"
    assert normalise_code("p-0420") == "P0420"
    assert normalise_code("00532") == "VAG00532"
    assert normalise_code("VAG 00532") == "VAG00532"
    assert normalise_code("boost pressure") is None


def test_make_aliases_match_the_reference_lookup():
    assert make_group("audi") == "VW_GROUP"
    assert make_group("skoda") == "VW_GROUP"
    assert make_group("seat") == "VW_GROUP"
    assert make_group("vauxhall") == "VAUXHALL_OPEL"
    assert make_group("land rover") == "JLR"
    assert make_group("mercedes-benz") == "MERCEDES"
    assert make_group("alfa romeo") == "FIAT"


def test_database_has_the_full_dataset():
    count = get_conn().execute("SELECT count(*) FROM codes").fetchone()[0]
    assert count == 84694


def test_p0300_has_the_full_guidance():
    result = search("P0300")
    assert result["normalised_code"] == "P0300"
    assert len(result["entries"]) == 1
    entry = result["entries"][0]
    assert entry["make"] == "GENERIC"
    assert "Misfire" in entry["description"]
    for key in ("meaning", "causes", "symptoms", "diagnosis", "fixes", "severity", "drive_advice"):
        assert entry["fields"][key]["available"], key
    assert "Serious" in entry["fields"]["severity"]["text"]
    assert entry["fields"]["drive_advice"]["text"]
    urls = " ".join(entry["source_urls"])
    assert "obdcodeslist.com" in urls
    assert "carparts.com" in urls
    assert "opendtc.net" in urls
    assert result["attribution"]["required_notice"].startswith("Code data from OBD Codes List")


def test_p0420_and_mistyped_po420():
    result = search("po420")
    assert result["normalised_code"] == "P0420"
    entry = result["entries"][0]
    assert "Catalyst" in entry["description"]
    assert "catalytic" in entry["fields"]["meaning"]["text"].lower()
    assert "Caution" in entry["fields"]["severity"]["text"]
    assert entry["fields"]["causes"]["available"]
    assert entry["fields"]["diagnosis"]["available"]
    assert entry["fields"]["fixes"]["available"]
    assert entry["fields"]["drive_advice"]["available"]


def test_ford_manufacturer_code_and_unfiltered_warning():
    ford = search("P1570", make="ford")
    assert ford["make_group"] == "FORD"
    assert ford["entries"][0]["relation"] == "selected"
    assert "INTAKE MANIFOLD" in ford["entries"][0]["description"]
    assert ford["entries"][0]["guidance_available"] is False

    wide = search("P1570")
    assert wide["warning"]
    assert "differs by make" in wide["warning"]
    assert len(wide["entries"]) > 1


def test_vag_five_digit_code_with_make_alias():
    result = search("00532", make="vw")
    assert result["normalised_code"] == "VAG00532"
    entry = result["entries"][0]
    assert entry["make"] == "VW_GROUP"
    assert entry["relation"] == "selected"
    assert entry["description"] == "Supply voltage"
    assert "VAG" in entry["notes"]


def test_vauxhall_also_returns_related_makes():
    row = get_conn().execute(
        """
        SELECT code FROM codes
        WHERE make='VAUXHALL_OPEL'
          AND code IN (SELECT code FROM codes WHERE make='GM')
          AND code IN (SELECT code FROM codes WHERE make='PEUGEOT_CITROEN')
        LIMIT 1
        """
    ).fetchone()
    assert row is not None
    result = search(row["code"], make="vauxhall")
    by_make = {entry["make"]: entry["relation"] for entry in result["entries"]}
    assert by_make["VAUXHALL_OPEL"] == "selected"
    assert by_make["GM"] == "related"
    assert by_make["PEUGEOT_CITROEN"] == "related"


def test_keyword_search_leads_with_the_generic_code():
    misfire = search("misfire")
    assert misfire["mode"] == "keyword"
    assert misfire["matches"][0]["code"] == "P0300"
    assert misfire["matches"][0]["make"] == "GENERIC"
    catalyst = search("catalytic converter")
    assert catalyst["matches"][0]["code"] == "P0420"
    ford = search("random misfire", make="Ford")
    assert all(match["make"] in {"FORD", "GENERIC"} for match in ford["matches"])
    assert ford["matches"][0]["code"] == "P0300"


def test_original_language_note_is_flagged():
    result = search("B1417", make="honda")
    entry = result["entries"][0]
    assert entry["original_language"] is True
    assert "original language" in entry["notes"].lower()


def test_unverified_wording_is_flagged_when_a_source_says_so():
    row = {column: "" for column in COLUMNS}
    row.update(
        {
            "code": "P0000",
            "letter": "P",
            "system": "Powertrain",
            "scope": "generic",
            "make": "GENERIC",
            "description": "Example",
            "description_source": "ocl_csv",
            "causes": "Loose connector",
            "causes_source": "ocl_pg: https://obdcodeslist.com/code/P0000.html",
            "notes": "No source recorded. unverified: written from the code definition alone",
            "source_urls": "[]",
        }
    )
    entry = serialise_entry(row, "generic")
    assert entry["notes_unverified"] is True
    row["causes"] = "unverified: written from the code definition alone\nLoose connector"
    flagged = serialise_entry(row, "generic")
    assert flagged["fields"]["causes"]["unverified"] is True
    assert "causes" in flagged["unverified_fields"]


def test_extract_codes_from_a_sentence_and_a_vag_make():
    assert extract_codes("The light came on with PO420") == ["P0420"]
    assert extract_codes("00532", make="Audi") == ["VAG00532"]
    assert extract_codes("mileage 00532", make="Ford") == []
    assert extract_codes("fault 00532 on the scan tool", make="Skoda") == ["VAG00532"]


def test_api_returns_p0300_p0420_and_a_make_code():
    p0300 = client.get("/api/codes", params={"q": "P0300"}).json()
    assert p0300["entries"][0]["fields"]["meaning"]["available"]
    assert p0300["entries"][0]["fields"]["fixes"]["available"]

    p0420 = client.get("/api/codes/P0420").json()
    assert p0420["normalised_code"] == "P0420"
    assert "catalytic" in p0420["entries"][0]["fields"]["meaning"]["text"].lower()

    ford = client.get("/api/codes", params={"q": "P1570", "make": "ford"}).json()
    assert "INTAKE MANIFOLD" in ford["entries"][0]["description"]
    assert ford["attribution"]["odbl_notice"]
    assert "ODbL" in ford["attribution"]["odbl_notice"]


def test_pages_and_existing_symptom_diagnosis():
    html = client.get("/codes")
    assert html.status_code == 200
    assert "Code data from OBD Codes List, https://obdcodeslist.com/code-data.html" in html.text
    assert "ODbL" in html.text
    assert "MIT" in html.text

    browser = client.get("/", headers={"accept": "text/html"})
    assert "Fault codes" in browser.text
    health = client.get("/")
    assert health.json()["status"] == "DA PERFORMANCE backend running"
    assert health.json()["fault_code_rows"] == 84694

    grind = client.post("/diagnose", json={"problem": "grinding on full lock", "vehicle": {"make": "Ford", "model": "Focus"}})
    body = grind.json()
    assert "CV joint" in body["summary"]
    assert body["severity"] == "medium"
    assert body["estimated_cost_min"] == 180
    assert "fault_code" not in body

    overheat = client.post("/diagnose", json={"problem": "overheating", "vehicle": {"make": "VW", "model": "Golf"}}).json()
    assert overheat["severity"] == "high"
    assert "thermostat" in overheat["summary"]


def test_diagnose_uses_the_dataset_for_a_fault_code():
    p0300 = client.post(
        "/diagnose",
        json={"problem": "P0300", "vehicle": {"make": "Audi", "model": "A4"}},
    ).json()
    assert "misfir" in p0300["summary"].lower()
    assert p0300["severity"] == "high"
    assert p0300["estimated_cost_min"] is None
    assert p0300["fault_code"]["normalised_code"] == "P0300"
    assert any("obdcodeslist.com" in (source.get("url") or "") for source in p0300["sources"])
    assert p0300["sources"][0]["snippet"].startswith("Code data from OBD Codes List")
    titles = " ".join(item["title"] for item in p0300["likely_causes"])
    assert "Diagnosis" in titles
    assert "Can I drive?" in titles

    mistyped = client.post("/diagnose", json={"problem": "po420", "vehicle": {"make": "Ford"}}).json()
    assert mistyped["fault_code"]["normalised_code"] == "P0420"
    assert "catalytic" in mistyped["summary"].lower()

    ford = client.post("/diagnose", json={"problem": "P1570", "vehicle": {"make": "Ford", "model": "Focus"}}).json()
    assert "INTAKE MANIFOLD" in ford["summary"]
    assert ford["fault_code"]["entries"][0]["make"] == "FORD"
