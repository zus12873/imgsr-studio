import io

from sqlalchemy import select
from sqlalchemy.orm import Session

from imgsr.auth import verify_password
from imgsr.cli import main
from imgsr.db.models import User
from imgsr.db.session import make_engine


def load_user(tmp_path, name):
    engine = make_engine(tmp_path / "db" / "imgsr.sqlite3")
    with Session(engine) as db:
        user = db.scalar(select(User).where(User.username == name))
    engine.dispose()
    return user


def test_create_user_and_reset_password(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO("password123\n"))
    assert main(["create-user", "bob", "--admin", "--quota", "7", "--password-stdin"]) == 0
    user = load_user(tmp_path, "bob")
    assert user.role == "admin" and user.daily_quota == 7
    assert verify_password(user.password_hash, "password123")
    monkeypatch.setattr("sys.stdin", io.StringIO("newpassword1\n"))
    assert main(["reset-password", "bob", "--password-stdin"]) == 0
    assert verify_password(load_user(tmp_path, "bob").password_hash, "newpassword1")


def test_errors_return_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert main(["create-user", "bob", "--password-stdin"]) == 1
    assert "密码至少 8 位" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO("password123\n"))
    assert main(["reset-password", "ghost", "--password-stdin"]) == 1


def test_duplicate_user(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO("password123\n"))
    assert main(["create-user", "bob", "--password-stdin"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("password123\n"))
    assert main(["create-user", "bob", "--password-stdin"]) == 1


def test_cleanup_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert main(["cleanup"]) == 0
    assert "已清理 0 个过期任务" in capsys.readouterr().out
