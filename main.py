import uvicorn
from fastapi import FastAPI

from app.api.router import auth, health, metrics, reservation, shows
from app.core.exceptions import DomainError, domain_error_handler
from app.core.metrics import HttpMetricsMiddleware

app = FastAPI(title="Seat Reservation")
app.add_middleware(HttpMetricsMiddleware)
app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(auth.router)
app.include_router(shows.router)
app.include_router(reservation.router)
app.add_exception_handler(DomainError, domain_error_handler)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
