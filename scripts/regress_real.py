"""Real-upstream regression: run the full pipeline on sample images through the actual relay.

Costs money (image + vision calls). Not part of pytest.

usage:
  uv run python scripts/regress_real.py IMG [IMG ...] [--truth-dir DIR] [--out data/regress]

Truth files are optional: <truth-dir>/<image stem>.txt. Without one, the raw transcription is
confirmed as-is (so the diff then only measures render fidelity against that transcription).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from imgsr.api.app import create_app
from imgsr.auth import hash_password
from imgsr.config import Settings
from imgsr.db.models import User


def wait(client: TestClient, task_id: str, done, timeout: float) -> dict:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while True:
        body = client.get(f"/api/tasks/{task_id}").json()
        if done(body):
            return body
        if time.monotonic() > deadline:
            raise SystemExit(f"timeout waiting for {task_id}: status={body['status']}")
        time.sleep(2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+", type=Path)
    ap.add_argument("--truth-dir", type=Path)
    ap.add_argument("--out", type=Path, default=Path("data/regress"))
    args = ap.parse_args()
    run_dir = args.out / time.strftime("%Y%m%d-%H%M%S")
    settings = Settings(data_dir=run_dir, cookie_secure=False, trusted_proxies="127.0.0.1/32")
    if not settings.open_api_key:
        print("OPEN_API_KEY 未配置（.env）", file=sys.stderr)
        return 2
    app = create_app(settings, maintenance=False)
    report = []
    with TestClient(app, client=("127.0.0.1", 50000), headers={"X-Requested-With": "imgsr"}) as client:
        with app.state.ctx.sf() as db:
            db.add(User(username="regress", password_hash=hash_password("regress-pass"),
                        role="admin", daily_quota=1000))
            db.commit()
        client.post("/api/auth/login", json={"username": "regress", "password": "regress-pass"}).raise_for_status()
        for image in args.images:
            started = time.monotonic()
            response = client.post("/api/tasks", files={"file": (image.name, image.read_bytes(), "image/png")})
            response.raise_for_status()
            task_id = response.json()["id"]
            body = wait(client, task_id, lambda b: b["status"] in ("awaiting_confirm", "transcribe_failed"), 600)
            truth = args.truth_dir / f"{image.stem}.txt" if args.truth_dir else None
            used_truth = bool(truth and truth.is_file())
            text = truth.read_text() if used_truth else (body["transcript_raw"] or "")
            client.put(f"/api/tasks/{task_id}/text", json={"confirmed_text": text}).raise_for_status()
            client.post(f"/api/tasks/{task_id}/rounds", json={}).raise_for_status()
            body = wait(client, task_id, lambda b: b["status"] in ("reviewed", "round_failed"), 1200)
            rnd = body["rounds"][-1]
            review = rnd.get("review") or {}
            if rnd["status"] == "succeeded":
                out = run_dir / f"{image.stem}-download.png"
                out.write_bytes(client.get(f"/api/files/{task_id}/download-{rnd['seq']}").content)
            entry = {
                "image": str(image), "source": [body["source_w"], body["source_h"]],
                "status": body["status"], "round_status": rnd["status"], "error": rnd["error"],
                "result": [rnd["result_w"], rnd["result_h"]], "download": [rnd["download_w"], rnd["download_h"]],
                "plan_mode": (rnd["strategy"].get("plan") or {}).get("mode"),
                "tiles": len((rnd["strategy"].get("plan") or {}).get("tiles", [])),
                "notes": (rnd["strategy"].get("plan") or {}).get("notes", []),
                "used_truth": used_truth, "diff_count": len(review.get("diffs", [])),
                "diffs": review.get("diffs", [])[:20],
                "suggestions": [s["action"] for s in review.get("suggestions", [])],
                "elapsed_total_s": round(time.monotonic() - started, 1),
            }
            report.append(entry)
            print(json.dumps(entry, ensure_ascii=False))
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"report: {run_dir / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
