import datetime
import os
from random import randint
from uuid import uuid4

from django.contrib.auth.hashers import check_password, make_password
from django.db.models import Q

from django.template.loader import render_to_string
from django.core.mail import send_mail
from faker import Faker


from rest_framework.response import Response
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from Users.models import User, ConfirmRequest, Token, UserIP
from inshop.settings import EMAIL_HOST_USER


def validate_permissions(token, refresh_token, role="admin"):
    """
    Функция проверки прав пользователя по токену
    """
    try:
        token = Token.objects.get(token=token)
        if token.expiration_date < datetime.date.today():
            refresh_token = Token.objects.get(token=refresh_token)
            if refresh_token.expiration_date < datetime.date.today():
                raise AuthenticationFailed(code=401, detail={"message": "Сессия истекла!"})
            token.expiration_date = datetime.date.today() + datetime.timedelta(days=7)
            refresh_token.expiration_date = datetime.date.today() + datetime.timedelta(days=14)
            token.save()
            refresh_token.save()
        user = token.user
    except:
        raise AuthenticationFailed(code=401, detail={"message": "Невалидный токен!"})
    roles = [role[0] for role in user.RoleChoices.choices]
    access = False
    for i in range(roles.index(user.role)+1):
        if roles[i] == role.lower():
            access = True
    if not access:
        raise PermissionDenied(detail={"message": "There are not enough permissions to perform this action!"})
    return user

def send_code(user, action="Подтвердите почту",
              action2="подтверждния почты",
              request_type=ConfirmRequest.RequestTypes.confirm,
              token=None):
    code = ''.join([str(randint(0, 9)) for _ in range(6)])
    ConfirmRequest.objects.filter(user=user).delete()
    ConfirmRequest.objects.create(user=user, code=code, type=request_type, token=token)
    html_version = 'email_message.html'
    action = "Gemups | " + action
    html_message = render_to_string(html_version,
                                    {
                                         "username": user.username,
                                         "action": action,
                                         "verification_code": code,
                                         "action_2": action2
                                     })
    send_mail(subject=action,
              message=None,
              html_message=html_message,
              from_email=EMAIL_HOST_USER,
              recipient_list=[user.email])
    return user


def base_authenticate(request, role, raise_exception=True):
    token = request.COOKIES.get("token")
    refresh_token = request.COOKIES.get("refresh_token")
    try:
        user = validate_permissions(token, refresh_token, role)
        ip_address = get_client_ip(request)
        if not UserIP.objects.filter(user=user, address=ip_address).exists():
            UserIP(user=user, address=ip_address).save()
    except Exception as e:
        if raise_exception:
            raise e
        return None, None
    return user, token


class UserNonRequiredAuthentication(BaseAuthentication):
    def authenticate(self, request):
        return base_authenticate(request, "temp_user", False)


class TempUserAuthentication(BaseAuthentication):
    def authenticate(self, request):
        return base_authenticate(request, "temp_user")



class UserAuthentication(BaseAuthentication):
    def authenticate(self, request):
        return base_authenticate(request, "user")


class RootAdminAuthentication(BaseAuthentication):
    def authenticate(self, request):
        return base_authenticate(request, "root-admin")


class SellerAuthentication(BaseAuthentication):
    def authenticate(self, request):
        return base_authenticate(request, "seller")


class AdminAuthentication(BaseAuthentication):
    def authenticate(self, request):
        request_data = request.data or request.query_params.dict()
        if request_data.get("model") == "AdminAction":
            return base_authenticate(request, "root-admin")
        return base_authenticate(request, "admin")


def set_root_admin():
    try:
        ADMIN_USERNAME = os.environ["ADMIN_USERNAME"]
        ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
        ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
    except:
        print("[ROOT-ADMIN] В .env нет данных рут-админки")
    else:
        try:
            admin = User.objects.get(username=ADMIN_USERNAME)
            admin.email = ADMIN_EMAIL
            if not check_password(ADMIN_PASSWORD, admin.password):
                admin.password = make_password(ADMIN_PASSWORD)
                print("[ROOT-ADMIN] Пароль изменён")
                admin.save()
        except:
            try:
                admin = User.objects.create(username=ADMIN_USERNAME, email=ADMIN_EMAIL,
                                             password=make_password(ADMIN_PASSWORD), role="root-admin", is_active=True)
                admin.save()
                print("[ROOT-ADMIN] Рут-админка добавлена")
            except Exception as e:
                print(f"[ROOT-ADMIN] Неизвестная ошибка:\n {e}")

def get_user(request):
    response = Response(status=200)
    user, _ = base_authenticate(request, "temp_user", False)
    if not user:
        exists = True
        username = None
        while exists:
            faker = Faker()
            username = f"{faker.user_name()}_{faker.last_name()}"
            exists = User.objects.filter(username=username).exists()
        user = User(username=username, password=make_password(str(uuid4())), role=User.RoleChoices.temp_user)
        user.save()
        expiration_date = datetime.date.today() + datetime.timedelta(days=360)
        token = Token.objects.create(user=user, token=uuid4(), expiration_date=expiration_date)
        response.set_cookie("token", token.token, expires=expiration_date.strftime("%a, %d-%b-%Y %H:%M:%S GMT"))
    return user, response


def get_seller_stat(transactions, seller):
    total_amount = round(sum([float(transaction.amount)-float(transaction.amount)*transaction.product.get_commission()
                        for transaction in transactions.filter(~Q(buyer=seller.user))]), 2)
    withdrawn_amount = round(sum([float(transaction.amount) for transaction in
                            transactions.filter(buyer=seller.user, seller=seller)]), 2)
    hold_amount = round(sum([float(transaction.amount)-float(transaction.amount)*transaction.product.get_commission()
                       for transaction in
                       transactions.filter(created_at=datetime.datetime.now() - datetime.timedelta(days=3))]), 2)
    credited_amount = round(float(total_amount) - float(hold_amount), 2)
    available_amount = round(float(credited_amount) - float(withdrawn_amount), 2)
    return {
            "available_amount": available_amount,
            "credited_amount": credited_amount,
            "withdrawn_amount": withdrawn_amount,
            "hold_amount": hold_amount,
            "total_amount": total_amount,
            "total_sales": transactions.exclude(buyer=seller.user).count()
        }


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]  # Берем первый IP из списка
    else:
        ip = request.META.get('REMOTE_ADDR')  # Иначе берем REMOTE_ADDR
    return ip


def on_start():
    set_root_admin()

on_start()

