"""Create gnucash file for new year including opening transactions based on previous year's file.

Method:
- the previous year's file is copied on filesystem level
- all transactions are deleted from the copied file
- opening transactions are added, with amounts taken from the previous year's file
"""

import argparse
import shutil
import sys

import gnucash
from gnucash.gnucash_core_c import ACCT_TYPE_EQUITY, ACCT_TYPE_INCOME, ACCT_TYPE_EXPENSE, ACCT_TYPE_TRADING, ACCT_TYPE_ROOT
from loguru import logger
from datetime import datetime
import json
import os

# Account types which are to be excluded from creating opening transactions
ACCOUNT_TYPES_TO_EXCLUDE = [
    ACCT_TYPE_INCOME,
    ACCT_TYPE_EXPENSE,
    ACCT_TYPE_TRADING,
    ACCT_TYPE_ROOT,
    ACCT_TYPE_EQUITY
]

def get_account_balances(book):
    """Get account balances.

    Get account balances for all accounts with type not in the exclude list. Descendants of excluded accounts
    are also excluded.
    """
    balances = {}
    root = book.get_root_account()

    def walk(account):
        yield account
        for child in account.get_children():
            yield from walk(child)

    for acc in walk(root):
        if acc.GetPlaceholder():
            continue
        if acc.GetType() in ACCOUNT_TYPES_TO_EXCLUDE:
            continue
        balances[acc.get_full_name()] = acc.GetBalance()

    return balances

def prepare_new_year_file(previous_file, new_file):
    """Create the new year's file by copying the previous year's file and deleting all transactions."""

    # Copy the previous year's file, do _not_ overwrite existing file
    if os.path.exists(new_file):
        raise FileExistsError(f"Target file {new_file} already exists.")
    logger.debug('Copying gnucash file.')
    shutil.copyfile(previous_file, new_file)

    # Open the new year's file with SESSION_NORMAL_OPEN flag
    logger.debug("Opening new year's gnucash file.")
    session_new = gnucash.Session(new_file, gnucash.SessionOpenMode.SESSION_NORMAL_OPEN)
    book_new = session_new.book

    # Delete all transactions
    logger.debug('Deleting all transactions.')
    root_account = book_new.get_root_account()
    accounts = root_account.get_descendants()

    for account in accounts:
        splits = account.GetSplitList()
        for split in splits:
            transaction = split.parent
            if transaction == None:
                logger.warning(f"Split without parent transaction found in account {account.get_full_name()}.")
                continue
            transaction.Destroy()

    return session_new

def main(previous_file, new_file, opening_date, config):
    """Create and populate new gnucash file.

    Args:
        previous_file: Path to previous year's gnucash file.
        new_file: Path to new year's gnucash file.
        opening_date: Date for the opening transactions.
        config: Configuration dictionary with keys:
            - equity_name: Name of the equity placeholder account.
            - equity_opening_name: Name of the equity opening balances account.
            - opening_transaction_text: Description text for opening transactions.
            - currency: Currency code for the transactions (e.g., "EUR").
    """

    equity_name = config['equity_name']
    equity_opening_name = config['equity_opening_name']
    opening_transaction_text = config['opening_transaction_text']
    currency = config['currency']

    # Prepare the new year's file
    logger.info(f"Creating new year's file {new_file} from previous year's file {previous_file}.")
    session_new = prepare_new_year_file(previous_file, new_file)

    # Open the previous year's file in read-only mode
    logger.info(f"Reading balances from previous year's file.")
    session_prev = gnucash.Session(previous_file, gnucash.SessionOpenMode.SESSION_READ_ONLY)
    book_prev = session_prev.book
    account_balances = get_account_balances(book_prev)

    # Open the existing new year's file in read-write mode
    book_new = session_new.book

    # Get the commodity (e.g., EUR) from provided currency
    transaction_currency = book_new.get_table().lookup("CURRENCY", currency)
    price_db = book_new.get_price_db()

    # Create or retrieve the Opening Balances account
    logger.info(f"Preparing opening balances counter account in new year's file.")
    root_account = book_new.get_root_account()
    logger.info(f"Looking up --{equity_name}--")
    equity_placeholder_account = root_account.lookup_by_full_name(equity_name)
    if not equity_placeholder_account:
        logger.info(f"Creating account: {equity_name}")
        equity_placeholder_account = gnucash.Account(book_new)
        equity_placeholder_account.SetName(equity_name)
        equity_placeholder_account.SetType(ACCT_TYPE_EQUITY)
        equity_placeholder_account.SetPlaceholder(True)
        root_account.append_child(equity_placeholder_account)

    # TODO: Handle multi-currency properly by creating sub-accounts for each currency. Do that on demand in the loop below.
    equity_opening_full_name = equity_name + "." + equity_opening_name
    logger.info(f"Looking up --{equity_opening_full_name}--")
    equity_account = root_account.lookup_by_full_name(equity_opening_full_name)
    if not equity_account:
        logger.info(f"Creating account: {equity_opening_name}")
        equity_account = gnucash.Account(book_new)
        equity_account.SetName(equity_opening_name)
        equity_account.SetType(ACCT_TYPE_EQUITY)
        equity_account.SetCommodity(transaction_currency)
        equity_placeholder_account.append_child(equity_account)

    # Create opening transactions in the new year's book for specified account types
    for account_name, balance in account_balances.items():
        if balance != 0:
            logger.info(f"Creating opening transaction for account {account_name}, amount: {balance}")
            account = book_new.get_root_account().lookup_by_full_name(account_name)
            if not account:
                # Create account if it does not exist in the new book
                account = gnucash.Account(book_new)
                account.SetName(account_name)
                book_new.get_root_account().append_child(account)

            # Create opening balance transaction
            transaction = gnucash.Transaction(book_new)
            transaction.BeginEdit()

            split_asset = gnucash.Split(book_new)
            split_asset.SetParent(transaction)
            split_asset.SetAccount(account)

            split_equity = gnucash.Split(book_new)
            split_equity.SetParent(transaction)
            split_equity.SetAccount(equity_account)

            asset_commodity = split_asset.GetAccount().GetCommodity()
            equity_commodity = split_equity.GetAccount().GetCommodity()

            equity_value = balance if (asset_commodity == equity_commodity) else price_db.convert_balance_nearest_price_t64(balance, asset_commodity, equity_commodity, opening_date)

            # Set the currency for the transaction
            transaction.SetDescription(opening_transaction_text)
            transaction.SetDate(opening_date.day, opening_date.month, opening_date.year)
            split_asset.SetAmount(balance)
            split_asset.SetValue(equity_value)

            split_equity.SetAmount(equity_value.neg())  # Opposite value to balance the transaction
            split_equity.SetValue(equity_value.neg())
            transaction.SetCurrency(transaction_currency)

            transaction.CommitEdit()

    # Save the new book
    logger.info(f"Saving new year's file")
    session_new.save()
    session_new.end()
    session_prev.end()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a new GnuCash file with opening transactions for a new year.")
    parser.add_argument("previous_file", help="The GnuCash file for the previous year.")
    parser.add_argument("new_file", help="The GnuCash file for the new year.")
    parser.add_argument("--config-file", default=None, help="Path to JSON config file (contains equity_name, equity_opening_name, opening_transaction_text, currency). Default is config.json.")
    parser.add_argument("--opening-date", default=None, help="The date for the opening transaction in ISO 8601 format (YYYY-MM-DD). If omitted, defaults to Jan 1 of the current year.")

    args = parser.parse_args()

    # Determine opening_date: use provided ISO date or default to Jan 1 of current year
    if args.opening_date is None:
        opening_date = datetime(datetime.now().year, 1, 1)
    else:
        opening_date = datetime.fromisoformat(args.opening_date)

    # Resolve config file path: if not provided, use config.json located next to this script
    if args.config_file is None:
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    else:
        config_path = args.config_file

    # Load config JSON from resolved path
    with open(config_path, 'r', encoding='utf-8') as _f:
        config = json.load(_f)

    try:
        main(args.previous_file, args.new_file, opening_date, config)

    except Exception as e:
        logger.error(f"Error, terminating program: {e}")
        sys.exit(1)
