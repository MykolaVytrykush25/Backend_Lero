import datetime
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.db import models
from django.db.models import Q

from rest_framework.exceptions import ValidationError
from django.core.files.base import ContentFile

import requests

from Main.utils import delete_file_from_s3, cryptomus_create_invoice, get_wallets_and_contracts_by_network, \
    upload_file_to_s3
from Main.celery import app
from Proxy.models import ProxyPurchase, ProxyTypes

from Users.models import Seller, User
from inshop.settings import REFERRAL_LEVELS, PRODUCTS_COMMISSIONS


class TransactionStatus(models.TextChoices):
    paid = "paid", "Оплачено"
    paid_over = "paid_over", "Оплачено больше"
    wrong_amount = "wrong_amount", "Недоплата"
    process = "process", "В процессе"
    confirm_check = "confirmation_check", "Проверка подтверждений"
    confirmations = "confirmations", "Подтверждения"
    wrong_amount_waiting = "wrong_amount_waiting", "Ожидание доплаты"
    check = "check", "Ожидание блокчейна"
    fail = "fail", "Ошибка оплаты"
    cancel = "cancel", "Отмена оплаты"
    system_fail = "system_fail", "Системная ошибка"
    refund_process = "refund_process", "Возврат в процессе"
    refund_fail = "refund_fail", "Ошибка возврата"
    refund_paid = "refund_paid", "Возврат проведён"
    locked = "locked", "Средства заблокированы из-за AML"


class PaymentType(models.TextChoices):
    balance = "balance", "Balance"
    cryptomus = "cryptomus", "Cryptomus"
    crypto = "crypto", "CustomPay"
    # bonus = "bonus", "Bonus from Gemups"
    stripe = "stripe", "Stripe(Card)"


class Product(models.Model):
    class ProductTypes(models.TextChoices):
        proxy = "proxy", "Прокси"
        account = "account", "Аккаунт"
        # kyc = "kyc", "Верификация кошелька"
        soft = "soft", "Софт"

    title = models.CharField(max_length=100)
    short_description = models.TextField(max_length=100, blank=True, null=True)
    description = models.TextField(max_length=250)
    photo = models.ForeignKey("File", models.SET_NULL, blank=True, null=True)
    prices = models.JSONField()
    seller = models.ForeignKey(Seller, on_delete=models.CASCADE)
    type = models.CharField(choices=ProductTypes.choices, db_index=True)
    categories = models.ManyToManyField("Category")
    tags = models.ManyToManyField("Tag")
    in_stock = models.IntegerField(blank=True, null=True)
    sold = models.IntegerField(default=0, db_index=True)
    is_popular = models.BooleanField(default=False)

    class Meta:
        db_table = 'products'

    def to_dict(self, user=None):
        seller_info = {"name": self.seller.user.username,
                       "id": self.seller.id,
                       "is_verified": self.seller.is_verified,
                       "photo": self.seller.user.avatar.url if self.seller.user.avatar else None}
        reviews = [review.rating for review in Review.objects.filter(product_id=self.pk)]
        rating = 0.0
        if reviews:
            rating = sum(reviews)/len(reviews)
        data = dict(
            id=self.pk, title=self.title, description=self.description,
            seller_info=seller_info,
            prices = [{"amount": price, "price": self.prices.get(price)} for price in self.prices],
            short_description=self.short_description,
            tags=[tag.to_dict() for tag in self.tags.all()],
            category=self.categories.last().name if self.categories.last() else None,
            sold=self.sold,
            rating=rating,
            unit=Units.get_unit(self),
            in_stock=self.in_stock,
            photo=self.photo.url if self.photo else None,
            review_access=False
        )
        if user:
            total_amount = sum(
                [purchase.amount for purchase in Purchase.objects.filter(
                    buyer_id=user.pk,
                    product_id=self.pk,
                    status__in=[
                        TransactionStatus.paid,
                        TransactionStatus.paid_over
                    ])]
                )
            if total_amount >= 10 and not Review.objects.filter(product_id=self.pk, user_id=self.pk).exists():
                data["review_access"] = True
        return data

    def get_price(self, quantity):
        quantity_list = [int(quantity) for quantity in self.prices.keys()]
        nearest_quantity = min(quantity_list, key=lambda x: abs(x-int(quantity)))
        price = self.prices.get(str(nearest_quantity))
        if quantity < nearest_quantity:
            price = self.prices.get(str(quantity_list[quantity_list.index(nearest_quantity)-1]))
        return price

    def get_commission(self):
        return PRODUCTS_COMMISSIONS.get(self.type)


class Tag(models.Model):
    name = models.CharField(max_length=25, unique=True)
    type = models.CharField(choices=Product.ProductTypes.choices)

    class Meta:
        db_table = 'tags'

    def to_dict(self):
        return dict(name=self.name, id=self.pk)


class Units:
    units_map = {
        Product.ProductTypes.proxy: "GB",
        Product.ProductTypes.account: "PC",
        # Product.ProductTypes.kyc: "PC",
        Product.ProductTypes.soft: "PC"
    }

    @classmethod
    def get_unit(cls, product):
        if product.type == Product.ProductTypes.proxy:
            if product.categories.last().name == ProxyTypes.ISP:
                return "PC"
        return cls.units_map.get(product.type)


class Category(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    type = models.CharField(choices=Product.ProductTypes.choices, max_length=100, blank=True, null=True)
    parent_category = models.ForeignKey("self", on_delete=models.CASCADE, blank=True, null=True)

    class Meta:
        db_table = 'categories'

    def to_dict(self):
        return dict(id=self.pk, name=self.name, description=self.description)


class ProductData(models.Model):
    purchase = models.ForeignKey("Purchase", models.SET_NULL, blank=True, null=True)
    data = models.TextField()
    is_sold = models.BooleanField(default=False, db_index=True)
    product = models.ForeignKey("Product", models.CASCADE)

    class Meta:
        db_table = "products_data"


class File(models.Model):
    class FileType(models.TextChoices):
        VIDEO = "video", "Видео"
        PHOTO = "photo", "Фото"

    url = models.URLField()
    type = models.CharField(choices=FileType.choices, default=FileType.PHOTO)

    class Meta:
        db_table = "files"

    def delete(self, using=None, keep_parents=False):
        delete_file_from_s3(self.url)
        return super().delete(using, keep_parents)


def get_exp_invoice():
    return datetime.datetime.now() + timedelta(hours=12)


class Invoice(models.Model):
    uuid = models.UUIDField(default=uuid4, unique=True)
    currency = models.CharField(blank=True, null=True)
    hash = models.CharField(blank=True, null=True)
    network = models.CharField(blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=3, db_index=True, blank=True, null=True)
    amount_usd = models.FloatField(db_index=True)
    amount_crypto = models.FloatField(db_index=True, blank=True, null=True)
    decimal = models.IntegerField(blank=True, null=True)
    expiration_dt = models.DateTimeField(default=get_exp_invoice, db_index=True)
    purchases = models.ManyToManyField("Purchase")
    is_active = models.BooleanField(default=False)
    balance_top_up = models.ForeignKey("BalanceTopUp", models.SET_NULL, blank=True, null=True)
    type = models.CharField(choices=[("balance", "Пополнение баланса"), ("purchase", "Покупка товара")],
                            default="purchase", db_index=True)

    def save(
        self,
        *args,
        force_insert=False,
        force_update=False,
        using=None,
        update_fields=None,
    ):
        if self.currency and self.network:
            max_invoice = Invoice.objects.filter(
                ~Q(purchases__status__in=[TransactionStatus.paid, TransactionStatus.paid_over]),
                ~Q(balance_top_up__status__in=[TransactionStatus.paid, TransactionStatus.paid_over]),
                amount_usd=self.amount_usd,
                expiration_dt__gte=datetime.datetime.now(), network=self.network, currency=self.currency
            ).exclude(id=self.pk).order_by("-amount").first()
            if self.currency != "USDT":
                url_binance = f"https://api.binance.com/api/v3/ticker/price?symbol={self.currency}USDT"
                data = requests.get(url_binance)
                data = data.json()
                self.amount_crypto = float(data["price"])
            else:
                self.amount_crypto = self.amount_usd
            self.amount = Decimal(self.amount_crypto)
            if max_invoice:
                self.amount = max_invoice.amount + Decimal(0.001)
            else:
                self.amount += Decimal(0.001)
            self.is_active = True
            self.expiration_dt = get_exp_invoice()
        return super().save(*args, force_insert=force_insert,
                            force_update=force_update,
                            using=using, update_fields=update_fields)

    def to_dict(self):
        to_address = None
        if self.currency and self.network:
            to_address = get_wallets_and_contracts_by_network(self.currency, self.network)
        return dict(uuid=self.uuid,
                    amount=self.amount,
                    amount_usd=self.amount_usd,
                    expiration_dt=self.expiration_dt,
                    currency=self.currency,
                    hash=self.hash,
                    network=self.network,
                    status=self.purchases.first().status if self.purchases.first() else self.balance_top_up.status,
                    to_address=to_address,
                    is_active=self.is_active)

    class Meta:
        db_table = 'invoices'


class Purchase(models.Model):
    uuid = models.UUIDField(blank=True, null=True)
    status = models.CharField(choices=TransactionStatus.choices,
                              default=TransactionStatus.check, db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    expired_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, blank=True, null=True)
    seller = models.ForeignKey(Seller, on_delete=models.CASCADE)
    buyer = models.ForeignKey(User, on_delete=models.CASCADE)
    provided = models.BooleanField(default=False)
    seller_message = models.TextField(blank=True, null=True, default="")
    buyer_message = models.TextField(blank=True, null=True)
    quantity = models.IntegerField(default=1)
    product_options = models.JSONField(blank=True, null=True)
    payment_type = models.CharField(choices=PaymentType.choices, default=PaymentType.cryptomus)
    txid = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'purchases'

    def save(
        self,
        *args,
        force_insert=False,
        force_update=False,
        using=None,
        update_fields=None,
    ):
        skip = False
        if args and args[0] == True:
            skip = True
        if not self.pk and not skip:
            if self.payment_type == PaymentType.balance:
                self.uuid = uuid4()
                self.save(True)
                balance = self.buyer.balance
                if balance < self.amount:
                    raise ValidationError({"message": "Insufficient balance!"})
                self.buyer.balance -= self.amount
                self.buyer.save()
                self.seller.user.balance += self.amount
                self.seller.user.save()
        return super().save(*args, force_insert=force_insert,
                            force_update=force_update,
                            using=using, update_fields=update_fields)

    def process(self):
        self.status = TransactionStatus.paid
        self.save()
        self.product.sold += 1
        self.product.save()
        if self.product.type == Product.ProductTypes.proxy:
            self.provided = True
            self.save()
            app.send_task(name="buy_proxy", route_name="buy_proxy", kwargs={"proxy_purchase": self.pk})
        elif self.product.type in [Product.ProductTypes.account, Product.ProductTypes.soft]:
            for i in range(self.quantity):
                product_data = ProductData.objects.filter(product_id=self.product.pk, is_sold=False).first()
                product_data.is_sold = True
                product_data.purchase_id = self.pk
                product_data.save()
                self.product.in_stock -= 1
                self.product.save()
                self.product.seller.balance += self.amount - self.amount*self.product.get_commission()
                self.product.seller.save()
                self.save()
            self.provided = True
            self.save()
        else:
            self.product.in_stock -= 1
            self.product.save()
        referral_amount = float(self.amount)-float(self.amount)*self.product.get_commission()
        ReferralTransaction.referral_calculation(
            self.buyer.referral_from,
            self.buyer,
            referral_amount,
            self.pk
        )


class BalanceTopUp(models.Model):
    uuid = models.UUIDField(unique=True, blank=True, null=True)
    status = models.CharField(choices=TransactionStatus.choices,
                              default=TransactionStatus.check, db_index=True)
    amount = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
    buyer = models.ForeignKey("Users.User", on_delete=models.PROTECT)
    payment_type = models.CharField(choices=PaymentType.choices, default=PaymentType.cryptomus)
    expiration_date = models.DateTimeField(blank=True, null=True)
    txid = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'balance_top_ups'

    def save(
        self,
        *args,
        force_insert=False,
        force_update=False,
        using=None,
        update_fields=None,
    ):
        if self.payment_type == PaymentType.cryptomus:
            skip = False
            if args and args[0] == True:
                skip = True
            if not self.pk and not skip:
                self.save(True)
                data = cryptomus_create_invoice(self.buyer.pk, self.amount)
                self.uuid = data.get("uuid")
                self.expiration_date = data.get("expiration_date")
        return super().save(*args, force_insert=force_insert,
                            force_update=force_update,
                            using=using, update_fields=update_fields)
    def process(self):
        self.status = TransactionStatus.paid
        self.save()
        self.buyer.balance += self.amount
        self.buyer.save()


class UserCart(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    amount = models.IntegerField(default=1)
    options = models.JSONField(blank=True, null=True)

    class Meta:
        db_table = 'users_carts'

    def set_amount(self, operation):
        product_cart = UserCart.objects.filter(~Q(id=self.pk), product=self.product, user=self.user)
        if self.options:
            product_cart = product_cart.filter(options=self.options)
        if product_cart:
            product_cart = product_cart.first()
            operations = {"+": self.amount+product_cart.amount,
                          "-": product_cart.amount-self.amount,
                          "=": self.amount}
            product_cart.amount = operations[operation]
            if product_cart.amount <= 0:
                product_cart.delete()
                return None
            product_cart.save()
            return product_cart
        if self.amount:
            return self.save()

    def save(
        self,
        *args,
        force_insert=False,
        force_update=False,
        using=None,
        update_fields=None,
    ):
        if self.amount <= 0 and self.pk:
            return self.delete()
        return super().save(*args, force_insert, force_update, using, update_fields)

    def to_dict(self):
        seller_info = {"name": self.product.seller.user.username,
                       "id": self.product.seller.id,
                       "is_verified": self.product.seller.is_verified,
                       "avatar": self.product.seller.user.avatar.url if self.product.seller.user.avatar else None}
        prices = self.product.prices
        product_data = dict(id=self.product.pk,
                            title=self.product.title,
                            type=self.product.type,
                            photo=self.product.photo.url if self.product.photo else None,
                            description=self.product.short_description,
                            prices=[{"amount": price, "price": prices.get(price)} for price in prices],
                            options=self.options)
        if self.options:
            country = self.options.get("country")
            if country:
                product_data["title"] += f" ({country})"
        return dict(product=product_data,
                    amount=self.amount, seller_info=seller_info)


class Review(models.Model):
    text = models.TextField(max_length=200)
    user = models.ForeignKey("Users.User", models.SET_NULL, null=True)
    product = models.ForeignKey("Main.Product", models.CASCADE)
    rating = models.IntegerField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reviews'

    def to_dict(self):
        return dict(text=self.text,
                    rating=self.rating,
                    created_at=self.created_at,
                    user=dict(
                        id=self.user.pk,
                        name=self.user.username,
                        avatar=self.user.avatar.url if self.user.avatar else None
                    ))


class ReferralTransaction(models.Model):
    class Types(models.TextChoices):
        accrual = "accrual", "Начисление"
        withdraw = "withdraw", "Вывод"

    from_user = models.ForeignKey("Users.User", models.SET_NULL,
                                  blank=True, null=True, related_name="from_user")
    to_user = models.ForeignKey("Users.User", models.SET_NULL,
                                blank=True, null=True, related_name="to_user")
    amount = models.FloatField(db_index=True)
    level = models.IntegerField(default=0)
    transaction = models.ForeignKey("Main.Purchase", models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    type = models.CharField(choices=Types.choices, default=Types.accrual, db_index=True)

    @staticmethod
    def referral_calculation(to_user, buyer, amount, purchase_id):
        i = 1
        for level in REFERRAL_LEVELS:
            if to_user:
                total_amount = sum([rt.amount for rt in ReferralTransaction.objects.filter(to_user=to_user)])
                if not total_amount >= 500:
                    amount = amount/100*level
                    if total_amount+amount > 500:
                        amount -= total_amount+amount-500
                    referral_transaction = ReferralTransaction(from_user=buyer, to_user=to_user,
                                                               amount=amount, level=i, transaction_id=purchase_id)
                    referral_transaction.save()
                from_user = to_user
                to_user = from_user.referral_from
                i += 1
    def save(
        self,
        *args,
        force_insert=False,
        force_update=False,
        using=None,
        update_fields=None,
    ):
        self.amount = round(self.amount, 2)
        return super().save(
            *args,
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields
        )


class AdminAction(models.Model):
    endpoint = models.CharField()
    user = models.ForeignKey(User, models.SET_NULL, blank=True, null=True)
    params = models.TextField()
    response_code = models.IntegerField()
    created_dt = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admin_actions"
