# Generated by Django 5.1.2 on 2024-10-28 16:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Main', '0029_tag_category'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='tag',
            name='category',
        ),
        migrations.AddField(
            model_name='tag',
            name='type',
            field=models.CharField(choices=[('proxy', 'Прокси'), ('account', 'Аккаунт'), ('kyc', 'Верификация кошелька')], default='proxy'),
            preserve_default=False,
        ),
    ]
