import datetime
import random
from uuid import uuid4

from django.db import models
from random import randint

def get_unique_referral_id():
    unique = False
    unique_ref_id = ""
    while not unique:
        unique_ref_id = "".join([str(randint(0,9)) for _ in range(6)])
        if not User.objects.filter(referral_link=unique_ref_id).exists():
            unique = True
    return unique_ref_id

class User(models.Model):
    class RoleChoices(models.TextChoices):
        temp_user = "temp_user", "Временный пользователь"
        user = "user", "Пользователь"
        seller = "seller", "Продавец"
        admin = "admin", "Администратор сайта"
        root_admin = "root-admin", "ГА сайта"

    class Locales(models.TextChoices):
        en = "en", "English"
        ru = "ru", "Russian"
        fr = "fr", "French"
        ja = "ja", "Japan"
        es = "es", "Espanol"
        ko = "ko", "Korean"
        ua = "ua", "Ukrainian" 
        de = "de", "German"
        zh = "zh", "hz"
        hi = "hi", "hello navernoe"
        ar = "ar", "Arabskiy"

    class Meta:
        db_table = 'users'

    products_cart = models.ManyToManyField("Main.Product", through="Main.UserCart")
    username = models.CharField(max_length=50, blank=True, null=True, unique=True)
    description = models.TextField(blank=True, null=True)
    email = models.EmailField(blank=True, null=True, unique=True)
    balance = models.FloatField(default=0)
    avatar = models.ForeignKey("Main.File", models.SET_NULL, blank=True, null=True, related_name="avatar")
    banner = models.ForeignKey("Main.File", models.SET_NULL, blank=True, null=True, related_name="banner")
    password = models.CharField()
    referral_from = models.ForeignKey("self", models.SET_NULL, blank=True, null=True)
    role = models.CharField(choices=RoleChoices.choices, default=RoleChoices.user)
    is_active = models.BooleanField(default=False)
    referral_link = models.CharField(default=get_unique_referral_id, unique=True, editable=False)
    locale = models.CharField(default="en", choices=Locales.choices)

    def save(
        self,
        *args,
        force_insert=False,
        force_update=False,
        using=None,
        update_fields=None,
    ):
        self.balance = round(self.balance, 2)
        return super().save(
            *args,
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields
        )

    def to_dict(self):
        data = dict(id=self.pk, username=self.username, email=self.email,
                    balance=self.balance, role=self.role, description=self.description,
                    avatar=self.avatar.url if self.avatar else None,
                    banner=self.banner.url if self.banner else None,
                    is_active=self.is_active,
                    referal_from={
                        "username": self.referral_from.username,
                        "id": self.referral_from.pk,
                        "avatar": self.referral_from.avatar.url if self.referral_from.avatar else None
                    } if self.referral_from else None,
                    referral_link=self.referral_link,
                    locale=self.locale,
                    is_seller=True if Seller.objects.filter(user_id=self.pk).exists() else False)
        return data

    def get_profile(self):
        data = dict(id=self.pk,
                    username=self.username,
                    description=self.description,
                    avatar=self.avatar.url if self.avatar else None,
                    banner=self.banner.url if self.banner else None)
        if self.role == User.RoleChoices.seller:
            seller = Seller.objects.filter(user_id=self.pk).first()
            if seller:
                data["seller_info"] = seller.to_dict()
        return data


class UserIP(models.Model):
    address = models.GenericIPAddressField()
    user = models.ForeignKey("User", models.CASCADE)


class TgUser(models.Model):
    user = models.ForeignKey("User", models.CASCADE)
    telegram_id = models.BigIntegerField(unique=True)
    first_name = models.CharField(max_length=50, blank=True, null=True)
    last_name = models.CharField(max_length=50, blank=True, null=True)


class Seller(models.Model):
    user = models.OneToOneField("User", on_delete=models.CASCADE)
    is_verified = models.BooleanField(default=False)
    balance = models.FloatField(default=0)

    class Meta:
        db_table = 'sellers'

    def to_dict(self):
        return dict(username=self.user.username, description=self.user.description,
                    is_verified=self.is_verified)

    def save(
        self,
        *args,
        force_insert=False,
        force_update=False,
        using=None,
        update_fields=None,
    ):
        self.balance = round(self.balance, 2)
        return super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
            *args
        )

class ConfirmRequest(models.Model):
    class RequestTypes(models.TextChoices):
        confirm = "confirm", "Подтверждение почты"
        reset = "reset-request", "Сброс пароля"
        password_set = "password-set", "Установка нового пароля"

    user = models.ForeignKey("User", on_delete=models.CASCADE)
    code = models.CharField()
    datetime = models.DateTimeField(auto_created=True, auto_now_add=True)
    type = models.CharField(choices=RequestTypes.choices, default=RequestTypes.confirm)
    token = models.UUIDField(blank=True, null=True)

    class Meta:
        db_table = "confirms"

    def validate(self):
        valid_datetime = datetime.datetime.now()-datetime.timedelta(minutes=10)
        return self.datetime.timestamp() > valid_datetime.timestamp()


class TgLink(models.Model):
    user = models.ForeignKey("User", on_delete=models.CASCADE)
    uuid = models.UUIDField(unique=True)


class Token(models.Model):
    user = models.ForeignKey("User", models.CASCADE)
    token = models.UUIDField()
    expiration_date = models.DateField()

    class Meta:
        db_table = 'tokens'
