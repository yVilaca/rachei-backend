from django.core.management.base import BaseCommand

from apps.e2e.seed import reset_and_seed


class Command(BaseCommand):
    help = 'Zera e semeia o mundo determinístico usado pelos testes E2E.'

    def handle(self, *args, **options):
        info = reset_and_seed()
        self.stdout.write(self.style.SUCCESS(
            f"E2E seed OK - grupo {info['group']['name']} com {info['alice']['email']} e {info['bob']['email']}"
        ))
