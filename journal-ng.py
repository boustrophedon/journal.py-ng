import argparse
from argparse import Namespace

from pathlib import Path

from contextlib import contextmanager
import datetime
from datetime import date, timezone
import getpass
import shlex
import sqlite3
from sqlite3 import Connection
import subprocess
import tempfile

import os
import sys

from typing import Iterator


# Config
EDITORCMD = "vim {filepath}"


HELPTEXT = """
An encrypted journal using sqlite3 and gpg.
"""

EPILOG = """
(c) 2022 Harry Stern and released under the MIT License <https://opensource.org/licenses/MIT>
"""

def spawn_editor(filepath):
    print(f"Opening temporary entry file {filepath}")
    try:
        command = shlex.split(EDITORCMD.format(filepath=filepath))
        subprocess.run(command, check=True)
    except OSError as err:
        if err.errno == 2:  # "No such file or directory", program doesn't exist.
            raise SystemExit("Editor command failed: File not found.")
        else:
            raise err

    # this lets you do whatever you want with the temp file before it's encrypted/deleted
    input("Press Enter when done.")

def write_encrypted_file(password: str, input_file: str, output_file: str):
    subprocess.run(["gpg", "--batch", "--passphrase-fd", "0", "--yes", "--quiet", "--output", output_file,
                    "--symmetric", "--cipher-algo", "AES256", input_file],
                    input=password,
                    text=True,
                    check=True)

def read_encrypted_file(password: str, input_file: str, output_file: str):
    subprocess.run(["gpg", "--batch", "--yes", "--quiet",
                    "--passphrase-fd", "0", "--pinentry-mode", "loopback",
                    "--output", output_file,
                    "--decrypt", input_file],
                    input=password,
                    text=True,
                    check=True)

def shred(path: str):
    if not (Path(path).name.startswith("entry.") or Path(path).name.startswith("db.")):
        raise SystemExit(f"Tried to shred a non-temporary file {path}. This is a programming error. Exiting.")
    subprocess.run(["shred", "--force", path], check=True)

@contextmanager
def encrypted_database(password: str, input_path: str, output_path: str, readonly: bool = False) -> Iterator[Connection]:
    temp_db = tempfile.NamedTemporaryFile(prefix="db.", dir=".")
    temp_db_path = temp_db.name

    read_encrypted_file(password, input_path, temp_db_path)
    conn = sqlite3.connect(temp_db_path)

    try:
        yield conn
        # write is inside the try block so that it only executes if the
        # operation inside the context executed successfully
        if not readonly:
            write_encrypted_file(password, temp_db_path, output_path)
    finally:
        conn.close()
        shred(temp_db_path)
        temp_db.close()

@contextmanager
def make_temp_entry_path(existing_entry: str | None, readonly: bool = False) -> Iterator[str]:
    ## Open entry temporary file in text mode to write entry
    # Disable auto-delete on close so that
    # 1. if something goes wrong you don't lose the entry.
    # 2. We can write the existing entry data to it, close it, and reopen with our editor

    temp_entry = tempfile.NamedTemporaryFile(mode='w+', prefix="entry.", dir=".", delete=False)
    temp_entry_path = temp_entry.name

    # If there's an existing entry, write that to the temporary file for editing
    if existing_entry:
        temp_entry.write(existing_entry)
    temp_entry.close()

    # If readonly, set file to readonly
    if readonly:
        Path(temp_entry_path).chmod(0o400)

    try:
        yield temp_entry_path
        shred(temp_entry_path)
        os.unlink(temp_entry_path)
    # os.unlink inside try and no finally because we want the entry to remain
    # if something fails during database/encryption operations
    finally:
        pass

def user_write_content(temp_entry_path: str) -> str:
    spawn_editor(temp_entry_path)
    content = None
    with open(temp_entry_path) as entry_file:
        content = entry_file.read()

    return content

def check_input_path(input_path: str):
    if not Path(input_path).exists():
        raise SystemExit(f"Input journal file {input_path} doesn't exist.")
    if not Path(input_path).is_file():
        raise SystemExit(f"Input journal file {input_path} is not a file.")

def parse_entry_date(entry_date: str | None) -> date | None:
    if entry_date:
        try:
            return datetime.date.fromisoformat(entry_date)
        except:
            raise SystemExit(f"The format for entries is YYY-MM-DD, got `{entry_date}`.")
    return None

def get_existing_entry(conn: Connection, entry_date: date | None) -> str | None:
    """ Fetches an existing entry from the journal. If entry_date is none, fetches the most recent entry.
        Returns None if no entry exists in the database on the given date.
    """
    existing_entry = None

    if not entry_date:
        rows = conn.execute("SELECT created FROM entries ORDER BY created DESC;").fetchall()
        if not rows:
            raise SystemExit("No journal entries exist; you must create one before editing it.")
        entry_date = datetime.date.fromisoformat(rows[0][0])


    rows = conn.execute("SELECT content FROM entries WHERE created = ?;", (entry_date,)).fetchall()
    if len(rows) > 1:
        raise SystemExit(f"Multiple entries were found in the database for \
                {entry_date}. This is a programming error and also violates the \
                sqlite unique constraint.")

    if len(rows) == 1:
        existing_entry = rows[0][0]

    return entry_date, existing_entry

def upsert_journal_entry(conn: Connection, created: str, modified: str, content: str):
    conn.execute("INSERT INTO entries values (?, ?, ?) \
            ON CONFLICT(created) DO UPDATE \
            SET modified=EXCLUDED.modified, \
                content=EXCLUDED.content;",
        (created, modified, content))



# very minor todo: this doesn't use the contextmanager I made for the db
# because that assumes the db already exists
def init_journal(ns: Namespace):
    output_file = ns.output if ns.output else "./encrypted-journal"

    if Path(output_file).exists():
        raise SystemExit(f"Output file {output_file} already exists.")

    with tempfile.NamedTemporaryFile(dir=".") as temp_db:
        temp_db_path = temp_db.name

        conn = sqlite3.connect(temp_db_path)

        # created: date iso, modified: datetime iso w/tz, content: text
        #
        # Note that we don't need to manually create an index as we only select
        # by created, which has an internal index due to the unique constraint
        conn.execute("CREATE TABLE entries (created TEXT UNIQUE, modified TEXT, content TEXT);")
        conn.commit()
        conn.close()

        password1 = getpass.getpass()
        password2 = getpass.getpass(prompt="Type password again: ")
        if password1 != password2:
            raise SystemExit("Passwords don't match, not creating journal file.")

        write_encrypted_file(password1, temp_db_path, output_file)

    print("Journal created sucessfully")


def edit_entry(ns: Namespace, readonly: bool = False):
    """
    Edit or create a new entry.
    """
    output_path = ns.output if ns.output else "./encrypted-journal"
    input_path = ns.input if ns.input else "./encrypted-journal"
    entry_date = ns.entry

    check_input_path(input_path)

    entry_date = parse_entry_date(entry_date)
    if not entry_date:
        # set via argparse with set_default
        # for `journal.py new`, default is today
        # for `journal.py edit|view`, no default so we get the latest entry
        # below in get_existing_entry
        entry_date = ns.default_date

    password = getpass.getpass()

    existing_entry = None
    with encrypted_database(password, input_path, output_path, readonly=readonly) as conn:
        entry_date, existing_entry = get_existing_entry(conn, entry_date)

    with make_temp_entry_path(existing_entry, readonly=readonly) as temp_entry_path:
        content = user_write_content(temp_entry_path)

        if not readonly:
            with encrypted_database(password, input_path, output_path) as conn:
                created = entry_date.isoformat()
                modified = datetime.datetime.now(timezone.utc).isoformat(timespec="seconds")
                upsert_journal_entry(conn, created, modified, content)
                conn.commit()

def migrate(ns: Namespace):
    output_path = ns.output if ns.output else "./encrypted-journal"
    input_path = ns.input if ns.input else "./encrypted-journal"
    input_dir = ns.dir

    check_input_path(input_path)

    files = [f for f in Path(input_dir).iterdir() if f.name.endswith("jrn")]

    password_old = getpass.getpass("Old journal file password: ")
    password_new = getpass.getpass("New journal db password: ")

    with encrypted_database(password_new, input_path, output_path) as conn:
        for file in files:
            content = None
            with make_temp_entry_path(None) as temp_jrn_path:
                read_encrypted_file(password_old, str(file), temp_jrn_path)
                with open(temp_jrn_path) as jrn_file:
                    content = jrn_file.read()

            created = file.name.split(".")[0][:10]

            mtime = file.stat().st_mtime
            mtime_dt = datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc)
            modified = mtime_dt.isoformat(timespec = "seconds")
            upsert_journal_entry(conn, created, modified, content)
            conn.commit()
            print(f"migrated {file}")
    print("done migration")


def sql_shell(ns: Namespace):
    input_path = ns.input if ns.input else "./encrypted-journal"
    output_path = ns.output if ns.output else "./encrypted-journal"

    check_input_path(input_path)
    temp_db = tempfile.NamedTemporaryFile(prefix="db.", dir=".")
    temp_db_path = temp_db.name

    password = getpass.getpass()
    read_encrypted_file(password, input_path, temp_db_path)
    subprocess.run(["sqlite3", temp_db_path])


def main():
    parser = argparse.ArgumentParser(description=HELPTEXT, epilog=EPILOG)
    parser.add_argument("-i", "--input", help="Read the journal from the given encrypted file")
    parser.add_argument("-o", "--output", help="Write the encrypted journal to the given file path")
    subparsers = parser.add_subparsers()

    parser.set_defaults(cmd=lambda x: parser.print_help())

    # Init
    init_parser = subparsers.add_parser("init", help="Create a new empty journal.")
    init_parser.set_defaults(cmd = init_journal)

    # New
    new_parser = subparsers.add_parser("new", help="Create a journal entry.")
    new_parser.set_defaults(cmd = lambda ns: edit_entry(ns, readonly=False))
    new_parser.set_defaults(default_date = datetime.date.today())

    new_parser.add_argument("entry", default=None, nargs="?",
        help="Journal date. The format is YYYY-MM-DD. Default is today.")

    # Edit
    edit_parser = subparsers.add_parser("edit", help="Edit a journal entry.")
    edit_parser.set_defaults(cmd = lambda ns: edit_entry(ns, readonly=False))
    edit_parser.set_defaults(default_date = None)

    edit_parser.add_argument("entry", default=None, nargs="?",
        help="Journal date. The format is YYYY-MM-DD. Default is latest.")

    # View
    view_parser = subparsers.add_parser("view", help="View a journal entry.")
    view_parser.set_defaults(cmd = lambda ns: edit_entry(ns, readonly=True))
    view_parser.set_defaults(default_date = None)

    view_parser.add_argument("entry", default=None, nargs="?",
        help="Journal date. The format is YYYY-MM-DD. Default is latest.")

    # Migrate
    migrate_parser = subparsers.add_parser("migrate", help="View a journal entry.")
    migrate_parser.set_defaults(cmd = migrate)

    migrate_parser.add_argument("dir", default=".", nargs="?",
        help="directory to migrate from")

    # Shell
    shell_parser = subparsers.add_parser("sql-shell", help="Debug: sql shell")
    shell_parser.set_defaults(cmd = sql_shell)

    # Test
    # test_parser = subparsers.add_parser("self-test", help="Debug: Run tests.")
    # test_parser.set_defaults(cmd=run_tests)

    args = parser.parse_args()
    args.cmd(args)

if __name__ == '__main__':
    main()


