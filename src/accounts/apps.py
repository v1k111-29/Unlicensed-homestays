from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"

    def ready(self) -> None:
        from accounts import signals  # noqa: F401  (connects the audit receivers)
