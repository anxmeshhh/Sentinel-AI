from pydantic import BaseModel


class HolidayOut(BaseModel):
    title: str
    date: str
    category: str  # national | regional | festival | observance
    states: list[str] | None
