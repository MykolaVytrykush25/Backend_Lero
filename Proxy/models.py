from datetime import timedelta
from django.db import models
from django.utils import timezone


class ProxyTypes(models.TextChoices):
    RESIDENTIAL = 'residential', 'RESIDENTIAL-PREMIUM',
    ISP = 'isp', 'ISP',
    DATA_CENTER = 'datacenter', 'SHARED-DATACENTER',


class ProxyProviders(models.TextChoices):
    LIGHTNING = 'lola', 'LOLA'
    BOB = 'bob', 'BOB',
    PROXY_SELLER = "ProxySeller", "Donald"
    PROXY_DROP_PULL_1 = "Joe"
    PROXY_DROP_PULL_2 = "Donald"
    PROVIDER711 = "seva"



def get_expiration_date():
    return timezone.now().date() + timedelta(days=30)


class ProxyPurchase(models.Model):
    class ProxyPurchaseStatus(models.TextChoices):
        PROCESS = 'process', "Processing"
        ACTIVE = 'active', 'Active'
        ENABLED = 'enabled', 'Enabled'
        EXPIRED = 'expired', 'Expired'
        BANDWIDTH_LEFT = "bandwith_left", "BANDWITH LEFT"

    purchase = models.ForeignKey("Main.Purchase", on_delete=models.CASCADE)
    created_date = models.DateTimeField(auto_now_add=True, null=True)
    expiration_date = models.DateTimeField(default=get_expiration_date, auto_created=True)
    service_data = models.JSONField(default=dict)
    country = models.CharField(default='', max_length=50, blank=True, null=True)
    count = models.IntegerField(default='', blank=False)
    type = models.ForeignKey("Main.Category", models.PROTECT)
    status = models.CharField(
        choices=ProxyPurchaseStatus.choices,
        max_length=50,
        default=ProxyPurchaseStatus.PROCESS
    )
    credentials_counter = models.IntegerField(default=0)
    extend_of = models.ForeignKey("self", models.CASCADE, blank=True, null=True, db_index=True)

    class Meta:
        db_table = 'proxy_purchases'

    def __str__(self):
        return f'Purchase of {self.type.name} by {self.purchase.buyer} on {self.created_date}'
