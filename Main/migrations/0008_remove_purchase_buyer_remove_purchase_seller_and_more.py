# Generated by Django 5.1.2 on 2024-10-18 13:04

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Main', '0007_alter_category_sub_category'),
        ('Users', '0004_confirmrequest_token'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='purchase',
            name='buyer',
        ),
        migrations.RemoveField(
            model_name='purchase',
            name='seller',
        ),
        migrations.RemoveField(
            model_name='purchase',
            name='transaction',
        ),
        migrations.AddField(
            model_name='transaction',
            name='buyer',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.CASCADE, to='Users.seller'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='transaction',
            name='message',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='transaction',
            name='quantity',
            field=models.IntegerField(default=1),
        ),
        migrations.AddField(
            model_name='transaction',
            name='seller',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.CASCADE, to='Users.user'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='product',
            name='seller',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='Users.seller'),
        ),
    ]
