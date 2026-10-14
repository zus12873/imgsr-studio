"""Run the app with fake relay clients for browser E2E tests (no network, no cost).

usage: uv run python scripts/e2e_server.py [--port 18091]
Serves frontend/dist (run `npm run build` in frontend/ first). Seeds admin/password123.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from imgsr.api.app import create_app  # noqa: E402
from imgsr.auth import hash_password  # noqa: E402
from imgsr.config import Settings  # noqa: E402
from imgsr.db.models import User  # noqa: E402
from imgsr.db.session import make_engine, migrate  # noqa: E402
from tests.fakes import FakeChat, FakeImages  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18091)
    args = parser.parse_args()
    data_dir = Path(tempfile.mkdtemp(prefix="imgsr-e2e-"))
    settings = Settings(_env_file=None, data_dir=data_dir, cookie_secure=False,
                        trusted_proxies="127.0.0.1/32", static_dir=ROOT / "frontend" / "dist")
    engine = make_engine(settings.db_path)
    migrate(engine)
    with Session(engine) as db:
        db.add(User(username="admin", password_hash=hash_password("password123"), role="admin", daily_quota=100))
        db.commit()
    engine.dispose()
    app = create_app(settings, images=FakeImages(scale=1.5), chat=FakeChat(lambda i, size: "示例原文。"),
                     retry_delays=(0.0, 0.0), maintenance=False)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
