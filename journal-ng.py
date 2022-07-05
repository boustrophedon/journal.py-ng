import argparse
from argparse import Namespace

import sqlite3
import tempfile
HELPTEXT = """
An encrypted journal using sqlite3 and gpg.
"""

EPILOG = """
(c) 2022 Harry Stern and released under the MIT License <https://opensource.org/licenses/MIT>
"""

def init_journal(ns: Namespace):
    pass

def new_entry(ns: Namespace):
    pass

def edit_entry(ns: Namespace, readonly: bool = False):
    pass

def run_tests(ns: Namespace):
    print("Running tests...")
    for fname, obj in globals().items():
        if fname.startswith("test_") and callable(obj):
            print(f"Running {fname}")
            obj()
    print("All tests passed.")

def main():
    parser = argparse.ArgumentParser(description=HELPTEXT, epilog=EPILOG)
    parser.add_argument("-i", "--input", help="Read the journal from the given encrypted file")
    parser.add_argument("-o", "--output", help="Write the encrypted journal to the given file path")
    subparsers = parser.add_subparsers()

    parser.set_defaults(cmd=lambda x: parser.print_help())

    # Init
    init_parser = subparsers.add_parser("init", help="Create a new empty journal.")
    init_parser.set_defaults(cmd=init_journal)

    # New
    new_parser = subparsers.add_parser("new", help="Create a journal entry.")
    new_parser.set_defaults(cmd=new_entry)

    # Edit
    edit_parser = subparsers.add_parser("edit", help="Edit a journal entry.")
    edit_parser.set_defaults(cmd = lambda ns: edit_entry(ns, False)) # readonly = False

    edit_parser.add_argument("entry", default=None, nargs="?",
        help="Journal file to edit. Default is latest.")


    # View
    view_parser = subparsers.add_parser("view", help="View a journal entry.")
    view_parser.set_defaults(cmd = lambda ns: edit_entry(ns, True)) # readonly = True

    view_parser.add_argument("entry", default=None, nargs="?",
        help="Journal file to view. Default is latest.")

    # Shell
    # TODO: drop you into an sqlite shell with the database open?

    # Test
    test_parser = subparsers.add_parser("self-test", help="Debug: Run tests.")
    test_parser.set_defaults(cmd=run_tests)

    args = parser.parse_args()
    args.cmd(args)

if __name__ == '__main__':
    main()


