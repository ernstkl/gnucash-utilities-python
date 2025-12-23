"""Create gnucash file for new year including opening transactions based on previous year's file."""

import argparse
import shutil
import gnucash
from gnucash.gnucash_core_c import ACCT_TYPE_EQUITY, ACCT_TYPE_ASSET, ACCT_TYPE_LIABILITY
from loguru import logger
from datetime import datetime

# Account types of top-level accounts whose decendents are to be
# considered for creating opening transactions
ACCOUNT_TYPES_TO_INCLUDE = [ACCT_TYPE_ASSET, ACCT_TYPE_LIABILITY]

def get_account_balances(book, account_types):
    """Get account balances.

    Get account balances, considering only top-level accounts of
    specified account types, and their descendants.
    """
    balances = {}
    root_account = book.get_root_account()
    top_level_accounts = [acc for acc in root_account.get_children() if acc.GetType() in account_types]

    for top_account in top_level_accounts:
        for account in top_account.get_descendants():
            if not account.GetPlaceholder():
                balances[account.get_full_name()] = account.GetBalance()
    return balances

def prepare_new_year_file(previous_file, new_file):
    """Create the new year's file by copying the previous year's file and deleting all transactions."""

    # Copy the previous year's file
    shutil.copyfile(previous_file, new_file)

    # Open the new year's file with SESSION_NORMAL_OPEN flag
    session_new = gnucash.Session(new_file, gnucash.SessionOpenMode.SESSION_NORMAL_OPEN)
    book_new = session_new.book

    # Delete all transactions
    root_account = book_new.get_root_account()
    accounts = root_account.get_descendants()

    for account in accounts:
        splits = account.GetSplitList()
        for split in splits:
            transaction = split.parent
            if transaction == None:
                continue;
            transaction.Destroy()

    return session_new

def main(previous_file, new_file, equity_name, equity_opening_name, opening_transaction_text, opening_date):
    # Prepare the new year's file
    logger.info(f"copying previous year's file {previous_file} to new file {new_file}")
    session_new = prepare_new_year_file(previous_file, new_file)

    # Open the previous year's file in read-only mode
    logger.info(f"reading balances from previous year's file")
    session_prev = gnucash.Session(previous_file, gnucash.SessionOpenMode.SESSION_READ_ONLY)
    book_prev = session_prev.book
    account_balances = get_account_balances(book_prev, ACCOUNT_TYPES_TO_INCLUDE)

    # Open the existing new year's file in read-write mode
    book_new = session_new.book

    # Get the commodity (e.g., EUR)
    transaction_currency = book_new.get_table().lookup("CURRENCY", "USD")
    price_db = book_new.get_price_db();

    # Create or retrieve the Opening Balances account
    logger.info(f"preparing opening balances counter account in new year's file")
    root_account = book_new.get_root_account()
    logger.info(f"looking up --{equity_name}--")
    equity_placeholder_account = root_account.lookup_by_full_name(equity_name)
    if not equity_placeholder_account:
        logger.info(f"creating account: {equity_name}")
        equity_placeholder_account = gnucash.Account(book_new)
        equity_placeholder_account.SetName(equity_name)
        equity_placeholder_account.SetType(ACCT_TYPE_EQUITY)
        equity_placeholder_account.SetPlaceholder(True)
        root_account.append_child(equity_placeholder_account)

    equity_opening_full_name = equity_name + "." + equity_opening_name
    logger.info(f"looking up --{equity_opening_full_name}--")
    equity_account = root_account.lookup_by_full_name(equity_opening_full_name)
    if not equity_account:
        logger.info(f"creating account: {equity_opening_name}")
        equity_account = gnucash.Account(book_new)
        equity_account.SetName(equity_opening_name)
        equity_account.SetType(ACCT_TYPE_EQUITY)
        equity_account.SetCommodity(transaction_currency)
        equity_placeholder_account.append_child(equity_account)

    # Create opening transactions in the new year's book for specified account types
    for account_name, balance in account_balances.items():
        if balance != 0:
            logger.info(f"creating opening balance for account {account_name}")
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
            equity_commodity = split_equity.GetAccount().GetCommodity();

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
    logger.info(f"saving new year's file")
    session_new.save()
    session_new.end()
    session_prev.end()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create opening transactions for a new year in GnuCash.")
    parser.add_argument("previous_file", help="The GnuCash file for the previous year.")
    parser.add_argument("new_file", help="The GnuCash file for the new year.")
    parser.add_argument("--equity_name", default="Equity", help="The name of top level equity account (placeholder).")
    parser.add_argument("--equity_opening_name", default="Opening balance", help="The name of the equity opening account.")
    parser.add_argument("--opening_transaction_text", default="Opening balance", help="The text for the opening transaction.")
    parser.add_argument("--opening_date", default="2025-01-01", help="The date for the opening transaction in ISO 8601 format (YYYY-MM-DD).")

    args = parser.parse_args()
    opening_date = datetime.fromisoformat(args.opening_date)
    main(args.previous_file, args.new_file, args.equity_name, args.equity_opening_name, args.opening_transaction_text, opening_date)
