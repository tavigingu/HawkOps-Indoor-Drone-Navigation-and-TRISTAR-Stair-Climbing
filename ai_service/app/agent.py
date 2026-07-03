import os
import base64
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types
from .models import HazardAnalysisResponse, PersonMedicalAnalysisResponse

# EnsureAPI key is available
load_dotenv()
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    # Avertisment pentru rularea locală fără cheie
    print("WARNING: GEMINI_API_KEY environment variable is not set. API calls will fail.")

client = genai.Client(api_key=api_key)
model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM_PROMPT = """You are an AI assistant integrated into a Search & Rescue drone. 
You are receiving an image frame from the drone's camera. Your job is to analyze the room and identify any potential hazards for human rescuers.

You MUST classify the room into exactly ONE of the following 5 hazard levels:
1. SAFE: Complet în siguranță, mediu curat.
2. CAUTION: Nereguli minore (obiecte căzute, praf), fără risc pentru viață.
3. DANGER: Pericole active (cabluri expuse, cioburi, obstacole mari).
4. CRITICAL: Haos masiv, compromitere structurală severă, acces extrem de dificil.
5. FATAL: Foc deschis, gaze toxice vizibile, prăbușire iminentă, letal.

Respond ONLY with valid JSON and exactly these keys:
- level: one of SAFE, CAUTION, DANGER, CRITICAL, FATAL
- hazards_identified: array of strings (empty array if none)
- description: required, non-empty, 1-2 concise sentences explaining why that level was chosen

If no hazards are visible, set hazards_identified to [] and description must still explain what was observed."""

PERSON_MEDICAL_PROMPT = """You are an AI medical triage assistant for Search & Rescue.
You receive a single image crop containing a person detected by the drone.

Classify the visible person's medical state into exactly one of:
- STABLE: no obvious severe injury signs visible
- INJURED: visible injury or distress, but not immediately life-threatening from visible cues
- CRITICAL: severe visible trauma or signs suggesting immediate life-threatening condition
- DECEASED: clear visual signs consistent with no signs of life
- UNKNOWN: visibility is insufficient to assess safely

Respond ONLY with valid JSON and exactly these keys:
- medical_state: one of STABLE, INJURED, CRITICAL, DECEASED, UNKNOWN
- indicators: array of short strings with visual cues used for assessment (empty if none)
- description: required, non-empty, 1-2 concise sentences

Never invent details not visible in the image. If uncertain, use UNKNOWN."""


def analyze_frame_for_hazards(base64_image: str) -> HazardAnalysisResponse:
    """
    Sends the base64 image to Gemini and returns the parsed HazardAnalysisResponse.
    """
    # Google GenAI SDK expects bytes for inline data
    image_bytes = base64.b64decode(base64_image)
    
    # Send request to Gemini - request JSON output and parse manually
    # (avoids Pydantic v2 $ref/$defs schema incompatibility with google-genai)
    response = client.models.generate_content(
        model=model_name,
        contents=[
            types.Part.from_bytes(
                data=image_bytes,
                mime_type='image/jpeg',
            )
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.2, # Low temperature for more deterministic/factual analysis
        ),
    )

    payload = json.loads(response.text or "{}")
    if "level" not in payload and "hazard_level" in payload:
        payload["level"] = payload.get("hazard_level")
    if "hazards_identified" not in payload or payload.get("hazards_identified") is None:
        payload["hazards_identified"] = []
    if "description" not in payload or payload.get("description") is None:
        hazards = payload.get("hazards_identified") or []
        level = payload.get("level", "CAUTION")
        if hazards:
            payload["description"] = f"Model returned level {level} with hazards: {', '.join(str(h) for h in hazards)}."
        else:
            payload["description"] = f"Model returned level {level} with no visible hazards identified."

    return HazardAnalysisResponse.model_validate(payload)


def analyze_person_medical_state(base64_image: str) -> PersonMedicalAnalysisResponse:
    """
    Sends a person image crop to Gemini and returns a medical-state assessment.
    """
    image_bytes = base64.b64decode(base64_image)

    response = client.models.generate_content(
        model=model_name,
        contents=[
            types.Part.from_bytes(
                data=image_bytes,
                mime_type='image/jpeg',
            )
        ],
        config=types.GenerateContentConfig(
            system_instruction=PERSON_MEDICAL_PROMPT,
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )

    payload = json.loads(response.text or "{}")
    if "medical_state" not in payload and "state" in payload:
        payload["medical_state"] = payload.get("state")

    if "indicators" not in payload or payload.get("indicators") is None:
        payload["indicators"] = []

    if "description" not in payload or payload.get("description") is None:
        med_state = payload.get("medical_state", "UNKNOWN")
        payload["description"] = f"Model returned medical_state {med_state}."

    return PersonMedicalAnalysisResponse.model_validate(payload)
