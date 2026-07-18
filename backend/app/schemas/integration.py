from pydantic import BaseModel


class ConnectTicketOut(BaseModel):
    ticket: str
