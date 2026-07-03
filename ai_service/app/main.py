from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from .models import HazardAnalysisRequest, HazardAnalysisResponse, PersonMedicalAnalysisResponse
from .agent import analyze_frame_for_hazards, analyze_person_medical_state

app = FastAPI(
    title="Search & Rescue AI Hazard Analysis API",
    description="Microservice for analyzing drone frames to detect room hazards",
    version="1.0.0"
)

# Optional: Add CORS middleware if the drone frontend needs to call this directly
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/v1/analysis/room-hazards", response_model=HazardAnalysisResponse)
async def analyze_room_hazards(request: HazardAnalysisRequest):
    """
    Analyzes a base64 encoded image frame and returns the hazard level.
    """
    try:
        # Pydantic will automatically validate that image_base64 exists in the request body
        result = analyze_frame_for_hazards(request.image_base64)
        return result
    except Exception as e:
        # Catch any Gemini API errors (like Missing API Key or Quota exceeded)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/analysis/person-medical", response_model=PersonMedicalAnalysisResponse)
async def analyze_person_medical(request: HazardAnalysisRequest):
    """
    Analyzes a base64 encoded person image and returns a medical state estimate.
    """
    try:
        result = analyze_person_medical_state(request.image_base64)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
