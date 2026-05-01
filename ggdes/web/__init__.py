"""Web interface for GGDes using FastAPI.

Provides a web UI for managing and viewing analyses, with real-time
updates and a modern, responsive interface.
"""

from fastapi import FastAPI

from ggdes.web.routes.analyses import router as analyses_router
from ggdes.web.routes.feedback import router as feedback_router
from ggdes.web.routes.worktrees import router as worktrees_router
from ggdes.web.routes.pages import router as pages_router
from ggdes.web.routes.ws import router as ws_router

app = FastAPI(title="GGDes Web", description="Web interface for GGDes analysis")

app.include_router(analyses_router)
app.include_router(feedback_router)
app.include_router(worktrees_router)
app.include_router(pages_router)
app.include_router(ws_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
