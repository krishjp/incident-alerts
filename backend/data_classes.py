from dataclasses import dataclass, asdict, field
from typing import List, Optional

@dataclass
class IncidentDetails:
    """Represents the detailed information found in the incident log."""
    raw_log: List[str] = field(default_factory=list)
    lat_lon: Optional[str] = None
    full_text_blob: str = ""

@dataclass
class Incident:
    """Represents a single traffic incident record."""
    number: str
    timestamp: str
    type: str
    location: str
    location_desc: str
    area: str
    details: IncidentDetails = field(default_factory=IncidentDetails)

    def to_dict(self):
        """Converts the object to a dictionary for JSON export."""
        return asdict(self)