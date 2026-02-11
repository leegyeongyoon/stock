"""Entry point for the auto-trading server."""

import uvicorn

from src.utils.logger import setup_logger


def main():
    setup_logger()
    uvicorn.run(
        "src.server.app:app",
        host="0.0.0.0",
        port=8088,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
