import logging

import gspread
import pandas
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)


logging.basicConfig(level=logging.DEBUG)


class GoogleSheetConnector:
    SCOPES = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive',
    ]

    def __init__(self, secret_key_path, share_with=None):
        """
        Create a new Google Sheet connector.

        :param os.Pathlike secret_key_path: The path to the secret key file.
        :param str share_with: The email address of an account where newly
            created sheets will be shared by default.
        """
        credentials = Credentials.from_service_account_file(secret_key_path)
        scoped_credentials = credentials.with_scopes(self.SCOPES)

        self.client = gspread.Client(scoped_credentials)
        self.client.session = AuthorizedSession(scoped_credentials)

        self.share_with = share_with

    def open(self, sheet_title, create=False):
        """
        Opens and returns a spreadsheet. Creates a new one if ``create`` is
        ``True``.

        :param str sheet_title: The title for the spreadsheet. It must be
            shared with the service account, unless a new one is to be created.
        :rtype: gspread.Spreadsheet
        """
        try:
            return self.client.open(sheet_title)
        except gspread.exceptions.SpreadsheetNotFound as e:
            # Only raise if we've been told not to create one:
            if not create:
                raise Exception(
                    'Spreadsheet {title} not found. Try sharing spreadsheet '
                    'with {email}'.format(
                        title=sheet_title,
                        email=self.creds._service_account_email
                    )
                ) from e

        if not self.share_with:
            raise Exception(
                'Creating sheets is not possible if "share_with" is unset.',
            )

        sheet = self.client.create(sheet_title)
        # NOTE: Sharing as 'owner'  fails, because service accounts seem to
        # have a different domain as gapps account (be careful editing this,
        # gspread fails SILENTLY!
        sheet.share(self.share_with, 'user', 'writer')

        logger.info('Created sheet "{}"".'.format(sheet.id))

        return sheet

    @staticmethod
    def _shape_to_range(dataframe, headers=True):
        """Returns a dataframe's shape as a gsheet range."""
        row_count, col_count = dataframe.shape
        if headers:
            return 1, 1, row_count + 1, col_count
        else:
            return 1, 1, row_count, col_count

    def write(self, sheet, dataframe, worksheet_number=1):
        """
        Write a dataframe into a spreadsheet

        :param gspread.Spreadsheet sheet: The target spreadsheet.
        :param pandas.DataFrame dataframe: The actual data to write to the
            sheet.
        :param int worksheet_number: The worksheet to read. Indexes start at 1.
        """
        worksheet = sheet.get_worksheet(worksheet_number - 1)

        col_indexes = {
            index: column_name
            for index, column_name in enumerate(dataframe.columns)
        }

        # Select a range (as big as the dataframe):
        cell_list = worksheet.range(*self._shape_to_range(dataframe))

        for cell in cell_list:
            if cell.row == 1:
                cell.value = col_indexes[cell.col - 1]
            else:
                # Substract 1 because gspread indexes start at 1.
                # Substract 2 to the row because we lost an extra row for the
                # header.
                cell.value = dataframe[col_indexes[cell.col - 1]][cell.row - 2]

        # Update in batch:
        worksheet.update_cells(cell_list)

    def read(self, sheet, worksheet_number=1, data_types=None):
        """
        Reads a sheet into a dataframe.

        :param gspread.Speadsheet sheet: The spreadsheet to read.
        :param int worksheet_number: The worksheet to read. Indexes start at 1.
        :param dict data_types: A dictionary of column headers -> data types,
            used to cast each column to a specify type.

        :rtype: pandas.DataFrame
        """
        worksheet = sheet.get_worksheet(worksheet_number - 1)

        contents = worksheet.get_all_records(head=1)
        columns = [col for col in worksheet.row_values(1) if col != '']
        dataframe = pandas.DataFrame(contents, columns=columns)

        if data_types is not None:
            for col, dtype in data_types.items():
                if col not in dataframe.columns:
                    raise KeyError(
                        "Dictionary dtypes's key '{col}' was not found "
                        "in sheet.".format(col=col)
                    )

                try:
                    dataframe[col] = dataframe[col].astype(dtype)
                except ValueError as e:
                    raise Exception(
                        'Column "{col}" could not be typecast as {dtype}'
                        .format(col=col, dtype=dtype)
                    ) from e
        return dataframe
