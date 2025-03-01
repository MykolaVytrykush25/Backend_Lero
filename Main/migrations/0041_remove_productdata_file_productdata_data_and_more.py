# Generated by Django 5.1.2 on 2024-11-04 23:02

import Main.models
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Main', '0040_productdata'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='productdata',
            name='file',
        ),
        migrations.AddField(
            model_name='productdata',
            name='data',
            field=models.TextField(default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='productdata',
            name='is_sold',
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name='productdata',
            name='product',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.CASCADE, to='Main.product'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='balancetopup',
            name='status',
            field=models.CharField(choices=[('paid', 'Оплачено'), ('paid_over', 'Оплачено больше'), ('wrong_amount', 'Недоплата'), ('process', 'В процессе'), ('confirmation_check', 'Проверка подтверждений'), ('confirmations', 'Подтверждения'), ('wrong_amount_waiting', 'Ожидание доплаты'), ('check', 'Ожидание блокчейна'), ('fail', 'Ошибка оплаты'), ('cancel', 'Отмена оплаты'), ('system_fail', 'Системная ошибка'), ('refund_process', 'Возврат в процессе'), ('refund_fail', 'Ошибка возврата'), ('refund_paid', 'Возврат проведён'), ('locked', 'Средства заблокированы из-за AML')], db_index=True, default='check'),
        ),
        migrations.AlterField(
            model_name='invoice',
            name='amount',
            field=models.DecimalField(db_index=True, decimal_places=6, max_digits=14),
        ),
        migrations.AlterField(
            model_name='invoice',
            name='expiration_dt',
            field=models.DateTimeField(db_index=True, default=Main.models.get_exp_invoice),
        ),
        migrations.AlterField(
            model_name='product',
            name='sold',
            field=models.IntegerField(db_index=True, default=0),
        ),
        migrations.AlterField(
            model_name='purchase',
            name='status',
            field=models.CharField(choices=[('paid', 'Оплачено'), ('paid_over', 'Оплачено больше'), ('wrong_amount', 'Недоплата'), ('process', 'В процессе'), ('confirmation_check', 'Проверка подтверждений'), ('confirmations', 'Подтверждения'), ('wrong_amount_waiting', 'Ожидание доплаты'), ('check', 'Ожидание блокчейна'), ('fail', 'Ошибка оплаты'), ('cancel', 'Отмена оплаты'), ('system_fail', 'Системная ошибка'), ('refund_process', 'Возврат в процессе'), ('refund_fail', 'Ошибка возврата'), ('refund_paid', 'Возврат проведён'), ('locked', 'Средства заблокированы из-за AML')], db_index=True, default='check'),
        ),
        migrations.AlterField(
            model_name='review',
            name='rating',
            field=models.IntegerField(db_index=True),
        ),
        migrations.AlterModelTable(
            name='productdata',
            table='products_data',
        ),
    ]
