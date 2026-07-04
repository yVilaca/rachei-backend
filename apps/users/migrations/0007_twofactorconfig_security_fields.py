from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_twofactorconfig_trusteddevice'),
    ]

    operations = [
        # Aumenta max_length do secret para acomodar Fernet token (~200 chars)
        migrations.AlterField(
            model_name='twofactorconfig',
            name='secret',
            field=models.CharField(max_length=512, db_column='tfa_secret'),
        ),
        # Anti-replay
        migrations.AddField(
            model_name='twofactorconfig',
            name='last_otp_counter',
            field=models.BigIntegerField(default=-1, db_column='tfa_last_otp_counter'),
        ),
        # Rate limiting por config
        migrations.AddField(
            model_name='twofactorconfig',
            name='otp_fail_count',
            field=models.IntegerField(default=0, db_column='tfa_otp_fail_count'),
        ),
        migrations.AddField(
            model_name='twofactorconfig',
            name='otp_locked_until',
            field=models.DateTimeField(null=True, blank=True, db_column='tfa_otp_locked_until'),
        ),
        # Último uso do dispositivo confiado
        migrations.AddField(
            model_name='trusteddevice',
            name='last_used_at',
            field=models.DateTimeField(null=True, blank=True, db_column='trd_ultimo_uso'),
        ),
    ]
