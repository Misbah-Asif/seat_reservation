import uvicorn
from fastapi import FastAPI

from app.api.router import auth, reservation, shows
from app.core.exceptions import DomainError, domain_error_handler

app = FastAPI(title="Seat Reservation")
app.include_router(auth.router)
app.include_router(shows.router)
app.include_router(reservation.router)
app.add_exception_handler(DomainError, domain_error_handler)


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
