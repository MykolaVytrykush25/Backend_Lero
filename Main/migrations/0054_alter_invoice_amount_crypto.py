# Generated by Django 5.1.2 on 2024-11-10 12:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Main', '0053_rename_purchase_amount_invoice_amount_crypto_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='invoice',
            name='amount_crypto',
            field=models.FloatField(blank=True, db_index=True, null=True),
        ),
    ]
