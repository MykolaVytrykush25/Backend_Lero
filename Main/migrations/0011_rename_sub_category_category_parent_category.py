# Generated by Django 5.1.2 on 2024-10-18 17:06

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('Main', '0010_alter_transaction_buyer_alter_transaction_seller'),
    ]

    operations = [
        migrations.RenameField(
            model_name='category',
            old_name='sub_category',
            new_name='parent_category',
        ),
    ]
