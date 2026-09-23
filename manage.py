"""Создание демонстрационных учётных записей вне исходного репозитория."""

import getpass
import sys

from werkzeug.security import generate_password_hash

from app import connect


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("customer", "editor"):
        raise SystemExit("Использование: python manage.py customer|editor логин")
    role, username = sys.argv[1:]
    password = getpass.getpass("Пароль (минимум 12 символов): ")
    if len(password) < 12:
        raise SystemExit("Пароль слишком короткий")
    with connect() as db:
        db.execute("INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
                   (username.lower(), generate_password_hash(password), role))
    print("Учётная запись создана:", username, role)


if __name__ == "__main__":
    main()
