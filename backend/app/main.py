from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth, profile, people, messages, email, jobs, outreach

app = FastAPI(
    title="NexusReach API",
    description="Smart personal networking assistant",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(people.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(email.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(outreach.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
