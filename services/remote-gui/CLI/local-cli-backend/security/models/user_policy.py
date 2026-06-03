from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime, timedelta
import uuid

from .base_policy import BasePolicy

class UserPolicyData(BaseModel):
    owner: str
    company: str
    type: Literal["admin", "user"]

class UserPolicy(BasePolicy):
    def __init__(self, data: UserPolicyData):
        self.data = data
        self.generated_fields = {
            "public_key": str(uuid.uuid4()),
            "expiration": (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"
        }

    def validate(self) -> bool:
        if not self.data.owner or not self.data.company:
            return False
        if self.data.type not in ["admin", "user"]:
            return False
        return True

    def to_dict(self):
        result = self.data.model_dump()
        result.update(self.generated_fields)
        return {"user": result}
