# gnucash-utilities-python

Python script(s) leveraging the GnuCash API to help with some tedious tasks.

Prerequisites:

For Ubuntu: `apt-get install gnucash python3-gnucash python3-loguru`

Other setups: you are on your own.

Note the python API will not work without a native gnucash installation

## Creating a new year's GnuCash file from the previous year's file

Script:`create_new_year_including_opening_transactions.py`

One way of handling multiple years in GnuCash is to use a separate
GnuCash file per year. For this setup, a new GnuCash file with
appropriate opening transactions needs to be created once the
accounting for the previous year has been completed.

This script performs that task, aiming to cover all
relevant accounts, no matter what the account tree structure is.

The script works by modifying a copy of the previous year's file. This
way the account structure with all details will be replicated
exactly. In addition, the learned rules for automatic assignment of
bank-statement transactions to GnuCash accounts will be available in
the new year's file.


