from sqlalchemy.orm import Session

from app.models.incident import Incident


class IncidentRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, incident: Incident, *, commit: bool = True) -> Incident:
        self.db.add(incident)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(incident)
        return incident
