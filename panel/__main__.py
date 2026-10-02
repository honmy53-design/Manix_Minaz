"""مانیکس / Manix project module."""

import os

import uvicorn

from .config import Settings
from .main import create_app

if __name__ == "__main__":
    settings = Settings.from_env()
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",
        port=settings.port,
        workers=1,
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "*"),
        timeout_graceful_shutdown=100,
        log_level="info",
    )
