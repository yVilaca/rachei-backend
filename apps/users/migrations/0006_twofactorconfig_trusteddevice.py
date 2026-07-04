import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0005_password_reset_code'),
    ]

    operations = [
        migrations.CreateModel(
            name='TwoFactorConfig',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False, db_column='tfa_id')),
                ('secret', models.CharField(max_length=64, db_column='tfa_secret')),
                ('is_active', models.BooleanField(default=False, db_column='tfa_ativo')),
                ('backup_codes', models.JSONField(default=list, db_column='tfa_backup_codes')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_column='tfa_criado_em')),
                ('updated_at', models.DateTimeField(auto_now=True, db_column='tfa_atualizado_em')),
                ('user', models.OneToOneField(
                    db_column='tfa_usuario_id',
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='two_factor_config',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'db_table': 'configs_2fa'},
        ),
        migrations.CreateModel(
            name='TrustedDevice',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False, db_column='trd_id')),
                ('token_hash', models.CharField(max_length=64, db_column='trd_token_hash')),
                ('user_agent', models.CharField(max_length=256, blank=True, db_column='trd_user_agent')),
                ('expires_at', models.DateTimeField(db_column='trd_expires_at')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_column='trd_criado_em')),
                ('user', models.ForeignKey(
                    db_column='trd_usuario_id',
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='trusted_devices',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'db_table': 'dispositivos_confiaveis',
                'indexes': [models.Index(
                    fields=['user', 'token_hash', 'expires_at'],
                    name='dispositivos_trd_idx',
                )],
            },
        ),
    ]
