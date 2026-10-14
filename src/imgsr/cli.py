"""`imgsr` command line: user management, maintenance and the web server."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys

from sqlalchemy import select

from imgsr.auth import end_user_sessions, hash_password
from imgsr.config import Settings
from imgsr.db.models import User
from imgsr.db.session import make_engine, make_session_factory, migrate
from imgsr.maintenance import cleanup_expired
from imgsr.storage import Storage

LOG_FORMAT = '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'


class CliError(Exception):
    pass


def _password(from_stdin: bool) -> str:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("密码：")
        if getpass.getpass("再输入一次：") != password:
            raise CliError("两次输入的密码不一致")
    if len(password) < 8:
        raise CliError("密码至少 8 位")
    return password


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="imgsr")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="新建用户")
    create.add_argument("username")
    create.add_argument("--admin", action="store_true")
    create.add_argument("--quota", type=int)
    create.add_argument("--password-stdin", action="store_true")
    reset = sub.add_parser("reset-password", help="重置密码")
    reset.add_argument("username")
    reset.add_argument("--password-stdin", action="store_true")
    sub.add_parser("cleanup", help="清理过期任务")
    serve = sub.add_parser("serve", help="启动 Web 服务")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve":
        import uvicorn

        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
        uvicorn.run("imgsr.api.app:create_app", factory=True, host=args.host, port=args.port,
                    proxy_headers=False, access_log=False)
        return 0
    settings = Settings()
    engine = make_engine(settings.db_path)
    try:
        migrate(engine)
        sf = make_session_factory(engine)
        with sf() as db:
            if args.command == "create-user":
                if db.scalar(select(User).where(User.username == args.username)) is not None:
                    raise CliError(f"用户 {args.username} 已存在")
                user = User(username=args.username, password_hash=hash_password(_password(args.password_stdin)),
                            role="admin" if args.admin else "user",
                            daily_quota=args.quota if args.quota is not None else settings.user_daily_default)
                db.add(user)
                db.commit()
                print(f"已创建用户 {user.username}（{user.role}）")
            elif args.command == "reset-password":
                user = db.scalar(select(User).where(User.username == args.username))
                if user is None:
                    raise CliError(f"用户 {args.username} 不存在")
                user.password_hash = hash_password(_password(args.password_stdin))
                db.commit()
                end_user_sessions(db, user.id)
                print(f"已重置 {user.username} 的密码")
            elif args.command == "cleanup":
                print(f"已清理 {cleanup_expired(sf, Storage(settings.files_dir))} 个过期任务")
    except CliError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0
