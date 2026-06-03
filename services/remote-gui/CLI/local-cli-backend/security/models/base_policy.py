from abc import ABC, abstractmethod
from typing import Dict, Any

class BasePolicy(ABC):
    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        ...

    @abstractmethod
    def validate(self) -> bool:
        ...
