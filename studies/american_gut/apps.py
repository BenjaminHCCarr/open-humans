from django.apps import AppConfig


class AmericanGutConfig(AppConfig):
    """
    Configure the American Gut study application.

    Note: The verbose_name matches the 'name' assigned for this study's API
    client. This is the 'name' field for its corresponding oauth2_provider
    Application, and was set by the setup_api management command in
    open_humans/management/commands/setup_api.py
    """
    name = 'studies.american_gut'
    verbose_name = 'American Gut'

    def ready(self):
        # Make sure our signal handlers get hooked up

        # pylint: disable=unused-variable
        import studies.american_gut.signals  # noqa