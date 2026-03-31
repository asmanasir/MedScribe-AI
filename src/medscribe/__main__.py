"""
Entry point: python -m medscribe

This lets you run the app directly during development.
In production, use: uvicorn medscribe.api.app:create_app --factory
"""

import uvicorn

from medscribe.config import get_settings


def main():
    settings = get_settings()
    uvicorn.run(
        "medscribe.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__":
    main()
