This is an updated version of my script [journal.py](https://github.com/boustrophedon/journal.py) from 10 years ago.

The major changes are:
- Instead of having one encrypted file per entry, there is only one encrypted file total, in addition to the script file.
- The encrypted file is an sqlite3 database, which stores a single table `entries`, whose columns are `created`,`modified`,`text`.
- The database file is encrypted with gpg --symmetric mode
- Use tempfile.NamedTemporaryFile instead of mkstemp
