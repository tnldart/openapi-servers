from abc import ABC, abstractmethod

class BaseSummarizer(ABC):
    @abstractmethod
    def summarize(self, data: str) -> dict:
        """Summarize data"""
        pass