from spendingsbot.bot import build_application
from spendingsbot.config import load_settings
from spendingsbot.google_sheets import create_workbook
from spendingsbot.repository import SpendingsRepository


def main() -> None:
    settings = load_settings()
    workbook = create_workbook(settings)
    repository = SpendingsRepository(
        workbook,
        trips_worksheet=settings.google_sheets_trips_worksheet,
        members_worksheet=settings.google_sheets_members_worksheet,
        spendings_worksheet=settings.google_sheets_spendings_worksheet,
    )
    repository.ensure_schema()

    application = build_application(settings.bot_token, repository)
    application.run_polling()


if __name__ == '__main__':
    main()
