from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Main', '0056_alter_invoice_amount'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='is_popular',
            field=models.BooleanField(default=False),
        ),
    ]
