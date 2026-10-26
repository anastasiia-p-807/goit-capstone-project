"""Explicit offline assignment of pre-account entries; run after backing up SQLite."""
import argparse
import os
from pathlib import Path
from .database import Database


def main():
    parser = argparse.ArgumentParser(description="Прив'язати старі записи без власника до наявного акаунта.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--database", type=Path, default=Path(os.getenv("STILL_DATABASE", "data/journal.sqlite3")))
    parser.add_argument("--apply", action="store_true", help="Без цього прапорця лише показує кількість записів.")
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error("Файл бази даних не існує.")
    with Database(args.database).connect() as conn:
        user = conn.execute("SELECT id FROM users WHERE username=?", (args.username.lower(),)).fetchone()
        if not user:
            parser.error("Акаунт не знайдено. Спочатку зареєструйте його в застосунку.")
        count = conn.execute("SELECT COUNT(*) FROM entries WHERE user_id IS NULL").fetchone()[0]
        if args.apply:
            conn.execute("UPDATE entries SET user_id=? WHERE user_id IS NULL", (user["id"],))
        print(f"{'Прив’язано' if args.apply else 'Доступно для прив’язки'}: {count}")


if __name__ == "__main__":
    main()
