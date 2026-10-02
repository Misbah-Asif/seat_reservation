import uvicorn
from fastapi import FastAPI

from app.api.router import shows

app = FastAPI(title="Seat Reservation")
app.include_router(shows.router)


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)