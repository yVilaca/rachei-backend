"""
Envia lembretes de parcelas em aberto — idempotente e seguro para rodar N vezes.

Uma parcela recebe lembrete quando:
  - está pendente (o devedor ainda deve; não conta a parcela auto-quitada do credor);
  - venceu há pelo menos LEMBRETE_APOS_DIAS;
  - nunca recebeu lembrete OU o último foi há mais de LEMBRETE_INTERVALO_DIAS.

Após enviar, grava `ultimo_lembrete_em` — então rodar duas vezes no mesmo dia
(retry, timer duplicado) não reenvia. Agendado por systemd timer / cron.

Uso:
    python manage.py enviar_lembretes            # envia
    python manage.py enviar_lembretes --dry-run  # só relata, não envia
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.debts.models import Installment
from apps.notifications import events as notif


class Command(BaseCommand):
    help = 'Envia lembretes de parcelas pendentes (idempotente).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Não envia; apenas relata.')

    def handle(self, *args, **options):
        dry = options['dry_run']
        agora = timezone.now()
        apos = timedelta(days=settings.LEMBRETE_APOS_DIAS)
        intervalo = timedelta(days=settings.LEMBRETE_INTERVALO_DIAS)

        limite_atraso = agora - apos       # criada antes disso → já venceu o prazo
        limite_reenvio = agora - intervalo  # último lembrete antes disso → pode reenviar

        parcelas = (
            Installment.objects
            .filter(status=Installment.STATUS_PENDING)
            .filter(debt__created_at__lte=limite_atraso)
            .filter(Q(ultimo_lembrete_em__isnull=True) | Q(ultimo_lembrete_em__lte=limite_reenvio))
            .select_related('debt', 'debt__paid_by', 'debtor')
        )

        enviados = 0
        for p in parcelas:
            if p.debtor_id == p.debt.paid_by_id:
                continue  # credor não deve a si mesmo
            dias = (agora - p.debt.created_at).days
            if not dry:
                notif.lembrete_pendente(
                    devedor=p.debtor, credor=p.debt.paid_by,
                    descricao=p.debt.description, valor_cents=p.amount_cents, dias=dias,
                )
                Installment.objects.filter(pk=p.pk).update(ultimo_lembrete_em=agora)
            enviados += 1
            self.stdout.write(
                f'{"[dry] " if dry else ""}lembrete -> devedor {p.debtor_id} '
                f'{p.debt.description} ({p.amount_cents}c, {dias}d)'
            )

        self.stdout.write(self.style.SUCCESS(
            f'{enviados} lembrete(s) {"a enviar" if dry else "enviado(s)"}.'
        ))
