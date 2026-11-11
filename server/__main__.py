"""python -m server 的启动入口。"""
from __future__ import annotations

import uvicorn

from server.config import HOST, PORT


def main() -> None:
    uvicorn.run("server.main:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
