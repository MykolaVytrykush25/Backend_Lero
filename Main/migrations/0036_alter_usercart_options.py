# Generated by Django 5.1.2 on 2024-10-31 15:13

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Main', '0035_usercart_options'),
    ]

    operations = [
        migrations.AlterField(
            model_name='usercart',
            name='options',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
