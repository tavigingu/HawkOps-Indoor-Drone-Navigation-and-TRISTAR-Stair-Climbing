from enum import Enum
from pydantic import BaseModel, Field
from typing import List


class HazardLevel(str, Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    DANGER = "DANGER"
    CRITICAL = "CRITICAL"
    FATAL = "FATAL"


class HazardAnalysisRequest(BaseModel):
    image_base64: str = Field(description="Base64 encoded image string of the frame to analyze")


class HazardAnalysisResponse(BaseModel):
    level: HazardLevel = Field(description="The assigned hazard level of the room")
    hazards_identified: List[str] = Field(description="List of specific hazards found in the image (e.g., exposed wires, fire)")
    description: str = Field(description="A short, concise description of the room's status and why the level was chosen")


class MedicalState(str, Enum):
    STABLE = "STABLE"
    INJURED = "INJURED"
    CRITICAL = "CRITICAL"
    DECEASED = "DECEASED"
    UNKNOWN = "UNKNOWN"


class PersonMedicalAnalysisResponse(BaseModel):
    medical_state: MedicalState = Field(description="Estimated medical state for the detected person")
    indicators: List[str] = Field(description="Visual indicators used by the model (e.g., bleeding, immobility)")
    description: str = Field(description="Short explanation for the estimated medical state")
