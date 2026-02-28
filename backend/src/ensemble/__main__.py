import uvicorn

from ensemble.config import settings

uvicorn.run("ensemble.main:app", host=settings.host, port=settings.port, reload=True)
