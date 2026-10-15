"""CSV ingest: reading, checking and saving uploaded or synthetic CSV files.

This is a plain Python package, not a Django app. The modules are:

- ``csvtools``: reads CSV bytes and checks the header and each cell. No database.
- ``parsers``: turns the checked rows of the three file types into plain row objects.
- ``load``: saves parsed rows to the database, all or nothing (used by the loader command).
- ``uploads``: the web upload rules: check, keep pending until confirmed, then save.
- ``views``: the upload pages; they handle HTTP and templates only.
"""
