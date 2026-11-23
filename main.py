from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/diagnose")
async def diagnose(data: dict):
    problem = (data.get("problem") or "").lower()
    vehicle = data.get("vehicle") or {}
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

@app.get("/")
def root():
    return {"status": "DA PERFORMANCE backend running"}
