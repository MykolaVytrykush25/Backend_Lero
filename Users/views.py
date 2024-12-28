import datetime
import hashlib
import hmac
import json
import logging

from datetime import timedelta
from math import ceil
from operator import itemgetter
from urllib.parse import parse_qsl
from uuid import uuid4

from django.apps import apps

from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, models
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from faker import Faker

from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.exceptions import ValidationError
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from drf_spectacular.utils import extend_schema, OpenApiParameter, inline_serializer, OpenApiResponse
from Main.models import BalanceTopUp, File, Purchase, Tag, PaymentType, TransactionStatus, \
    Invoice, ReferralTransaction, Product, Review, AdminAction
from Main.serializers import PhotoUploadSerializer, CategorySerializer
from Users.utils import send_code, TempUserAuthentication, SellerAuthentication, get_seller_stat, base_authenticate, \
    get_client_ip, UserNonRequiredAuthentication

from Proxy.providers import gift_proxy_plan
from Main.utils import check_captcha, get_object_or_404, upload_file_to_s3, FieldsTypeSerializer, ResponseLocale, \
    stripe_create_invoice
from Users.models import User, Token, ConfirmRequest, Seller, TgUser, TgLink, UserIP, get_unique_referral_id
from Users.serializers import UserSerializer
from Users.utils import UserAuthentication, validate_permissions, AdminAuthentication
from inshop.settings import TG_BOT_TOKEN, BOT_USERNAME, COOKIE_DOMAIN, TG_SECRET_KEY


@extend_schema(tags=["Пользователи"])
class UserViewSet(GenericViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    authentication_classes = [UserNonRequiredAuthentication]

    @extend_schema(parameters=[inline_serializer("GetProfile", fields={
        "id": serializers.IntegerField(required=False),
        "username": serializers.CharField(required=False)
    })])
    @action(methods=["GET"], detail=False, url_path="get-profile",
            authentication_classes=[UserNonRequiredAuthentication])
    def get_profile(self, request: Request):
        filters = Q(id=request.query_params.get("id"))
        if request.query_params.get("username"):
            filters |= Q(username=request.query_params.get("username"))
        user = get_object_or_404(
            User, filters
        )
        user_data = user.get_profile()
        if user.role == User.RoleChoices.seller:
            seller = get_object_or_404(Seller, user=user)
            seller_reviews = Review.objects.filter(
                product__seller=seller
            )
            user_data["seller_info"].update(dict(seller_rating=sum(
                [review.rating for review in seller_reviews]
            )/seller_reviews.count() if seller_reviews.count() else 0.0,
                                                 total_sales=Purchase.objects.filter(
                                                    seller=seller,
                                                    status=TransactionStatus.paid
                                                 ).count()))
        return ResponseLocale(user=request.user, status=200, data=user_data)

    @extend_schema(parameters=[OpenApiParameter(location=OpenApiParameter.COOKIE, name="token"),
                               inline_serializer(name="UserGetSerializer",
                                                 fields={"id": serializers.IntegerField(required=False),
                                                         "username": serializers.CharField(required=False)})],
                   responses={200: OpenApiResponse(response=inline_serializer("UserGetResponse", fields={
                       "username": serializers.CharField(),
                       "email": serializers.EmailField(),
                       "role": serializers.ChoiceField(choices=User.RoleChoices.choices),
                       "balance": serializers.DecimalField(max_digits=10, decimal_places=2),
                   }))})
    @action(methods=["GET"], detail=False, url_path="get", authentication_classes=[TempUserAuthentication])
    def get(self, request: Request):
        token = request.COOKIES.get("token")
        refresh_token = request.COOKIES.get("refresh_token")
        user_id = request.query_params.get("id")
        username = request.query_params.get("username")
        if user_id or username:
            try:
                validate_permissions(token, refresh_token, "admin")
            except:
                return ResponseLocale(user=request.user, status=403, data={"message": "Access is denied!"})
            user = get_object_or_404(User, id=user_id, username=username)
        else:
            user = request.user
        user_data = user.to_dict()
        tg_user = TgUser.objects.filter(user_id=user.pk).first()
        if tg_user:
            user_data["social_type"] = "telegram"
        response = Response(status=200, data=user_data)
        try:
            token_obj = Token.objects.get(token=token)
            refresh_token_obj = Token.objects.get(token=refresh_token)
            response.set_cookie("token", token_obj.token,
                                expires=token_obj.expiration_date.strftime("%a, %d-%b-%Y %H:%M:%S GMT"),
                                httponly=True)
            response.set_cookie("refresh_token", refresh_token_obj.token,
                                expires=refresh_token_obj.expiration_date.strftime("%a, %d-%b-%Y %H:%M:%S GMT"),
                                httponly=True)
        except:
            pass
        return response

    @extend_schema(request=inline_serializer(name="UserAddSerializer",
                                             fields={"email": serializers.EmailField(required=True),
                                                     "password": serializers.CharField(required=True),
                                                     "username": serializers.CharField(required=True),
                                                     "referral_link": serializers.UUIDField(required=False)
                                                     }))
    @action(methods=["POST"], detail=False,
            parser_classes=[JSONParser],
            authentication_classes=[UserNonRequiredAuthentication])
    def register(self, request):
        """
        Функция регистрации пользователя
        """
        check_captcha(request.data.get("captcha"))
        ip_address = get_client_ip(request)
        if UserIP.objects.filter(address=ip_address).count() >= 3:
            return ResponseLocale(user=request.user, status=400, data={"message": "Too many accounts on the same ip!"})
        referral_link = request.data.get("referral_link")
        if referral_link:
            user = User.objects.filter(referral_link=referral_link).first()
            request.data["referral_from"] = user.pk if user else None
        user_serializer = self.serializer_class(data=request.data)
        try:
            user_serializer.is_valid(raise_exception=True)
            user = user_serializer.create(user_serializer.validated_data)
        except IntegrityError:
            return ResponseLocale(user=request.user, status=400, data={"message": "Error when register user!"})
        UserIP(user=user, address=ip_address).save()
        return ResponseLocale(user=request.user, status=200, data={"message": "Registration successful!"})

    @action(methods=["PATCH"], detail=False, url_path="change-referral-link",
            authentication_classes=[TempUserAuthentication])
    def change_referral_link(self, request):
        request.user.referral_link = get_unique_referral_id()
        request.user.save()
        return ResponseLocale(user=request.user, status=200, data={"message": "The referral link has been changed"})

    @action(methods=["POST"], detail=False, url_path="send-code",
            authentication_classes=[UserAuthentication])
    def send_verify_code(self, request: Request):
        if request.user.is_active:
            return ResponseLocale(user=request.user, status=201, data={"message": "You have already confirmed your email!"})
        send_code(request.user, "Подтвердите ваш адрес электронной почты!",
                  "подтверждения аккаунта",
                  "confirm-email")
        return ResponseLocale(user=request.user, status=200, data={"message": "The OTP code has been sent to the post office!"})

    @staticmethod
    def check_webapp_signature(init_data):
        try:
            parsed_data = dict(parse_qsl(init_data))
            print(parsed_data)
        except ValueError:
            raise ValidationError({"message": "Invalid hash!"})
        if "hash" not in parsed_data:
            raise ValidationError({"message": "Invalid hash!"})
        hash_ = parsed_data.pop('hash')
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed_data.items(), key=itemgetter(0))
        )
        secret_key = hmac.new(
            key=b"WebAppData", msg=TG_BOT_TOKEN.encode(), digestmod=hashlib.sha256
        )
        calculated_hash = hmac.new(
            key=secret_key.digest(), msg=data_check_string.encode(), digestmod=hashlib.sha256
        ).hexdigest()
        if calculated_hash != hash_:
            raise ValidationError({"message": "Invalid hash!"})
        return parsed_data

    @staticmethod
    def _login_telegram(user_info):
        tg_user = TgUser.objects.filter(telegram_id=user_info.get("id")).first()
        if not tg_user:
            username = user_info.get("username")
            if not username:
                faker = Faker()
                username = user_info.get("first_name", faker.user_name())
            photo = None
            if user_info.get("photo_url"):
                photo = File(type=File.FileType.PHOTO, url=user_info.get("photo_url"))
                photo.save()
            user = User(username=username, password=make_password(str(uuid4())),
                        role=User.RoleChoices.user, avatar=photo)
            user.save()
            tg_user = TgUser(telegram_id=user_info.get("id"),
                             user=user,
                             first_name=user_info.get("first_name"),
                             last_name=user_info.get("last_name"))
            tg_user.save()
            # gift_proxy_plan.apply_async(args=tg_user.pk, eta=datetime.datetime.now() + timedelta(minutes=1))
        else:
            return tg_user.user
        return user


    @extend_schema(request=inline_serializer(name="UserLoginSerializer",
                                             fields={"email": serializers.EmailField(required=True),
                                                     "password": serializers.CharField(required=True)}),
                   responses={200: OpenApiResponse(response=inline_serializer("LoginResponse", fields={
                       "username": serializers.CharField(),
                       "email": serializers.EmailField()
                       }))}
                   )
    @action(methods=["POST"], detail=False, parser_classes=[JSONParser],
            authentication_classes=[UserNonRequiredAuthentication])
    def login(self, request):
        """
        Функция авторизации пользователя
        """
        if request.data.get("from") == "telegram":
            init_data = self.check_webapp_signature(request.data.get("queryString"))
            user_info = json.loads(init_data.get("user"))
            user = self._login_telegram(user_info)
        else:
            check_captcha(request.data.get("captcha"))
            email = request.data.get("email")
            password = request.data.get("password")
            try:
                user = User.objects.get(Q(email=email) | Q(username=email))
            except:
                return ResponseLocale(user=request.user, status=400, data={"message": "Invalid email or password!"})
            if not check_password(password, user.password):
                return ResponseLocale(user=request.user, status=400, data={"message": "Invalid email or password!"})
        expiration_date = datetime.date.today() + datetime.timedelta(days=6)
        refresh_expiration_date = datetime.date.today() + datetime.timedelta(days=14)
        token = Token.objects.create(user=user, token=uuid4(), expiration_date=expiration_date)
        refresh_token = Token.objects.create(user=user, token=uuid4(), expiration_date=refresh_expiration_date)
        response = Response(status=200, data={"email": user.email, "username": user.username})
        response.set_cookie("token", token.token,
                            expires=expiration_date.strftime("%a, %d-%b-%Y %H:%M:%S GMT"),
                            httponly=True, domain=COOKIE_DOMAIN)
        response.set_cookie(
            "refresh_token", refresh_token.token,
            expires=refresh_expiration_date.strftime("%a, %d-%b-%Y %H:%M:%S GMT"),
            httponly=True, domain=COOKIE_DOMAIN
        )
        return response

    @extend_schema(request=None,
                   parameters=[OpenApiParameter(location=OpenApiParameter.COOKIE, name="token")],
                   responses=None)
    @action(methods=["POST"], detail=False, parser_classes=[JSONParser],
            authentication_classes=[TempUserAuthentication])
    def logout(self, request: Request):
        response = Response(status=200, data={"message": "Logout successful!"})
        token = Token.objects.get(token=request.auth)
        response.delete_cookie("token")
        token.delete()
        return response

    @extend_schema(parameters=[inline_serializer("GetBalanceTransactions", fields={
        "limit": serializers.IntegerField(),
        "page": serializers.IntegerField(),
        "statuses": serializers.CharField(required=False)
    })])
    @action(methods=["GET"], detail=False, url_path="get-balance-transactions",
            authentication_classes=[TempUserAuthentication])
    def get_balance_transactions(self, request: Request):
        try:
            limit = int(request.query_params["limit"])
            page = int(request.query_params["page"])
        except (KeyError, ValueError):
            return ResponseLocale(user=request.user, status=400, data={"message": "Missed required parameters - limit or page!"})
        filters = []
        statuses = request.query_params.get("statuses")
        if statuses:
            filters.append(Q(status__in=statuses.split(",")))
        transactions = BalanceTopUp.objects.filter(buyer=request.user, *filters).order_by("-created_at")
        count = transactions.count()
        transactions = transactions[(page-1)*limit:page*limit]
        data = []
        for transaction in transactions:
            if transaction.status != TransactionStatus.paid:
                if transaction.created_at.timestamp() < (
                        datetime.datetime.now() - datetime.timedelta(hours=12)).timestamp():
                    transaction.status = TransactionStatus.cancel
                    transaction.save()
            transaction_data = {
                "amount": transaction.amount,
                "status": transaction.status,
                "created_dt": transaction.created_at,
                "payment_type": transaction.payment_type,
            }
            if transaction.payment_type == PaymentType.cryptomus:
                transaction_data["invoice"] = f"https://pay.cryptomus.com/pay/{transaction.uuid}"
            if transaction.payment_type == PaymentType.crypto:
                transaction_data["invoice"] = f"https://pay.gemups.com/pay/{transaction.uuid}"
            if transaction.expiration_date:
                if (transaction.status == TransactionStatus.check and
                        transaction.expiration_date.timestamp() > datetime.datetime.now().timestamp()):
                    transaction_data["expiration_dt"] = transaction.expiration_date.strftime("%a, %d-%b-%Y %H:%M:%S GMT")
            data.append(transaction_data)
        return ResponseLocale(user=request.user, status=200, data={"transactions": data, "total_pages": ceil(count/limit)})

    @extend_schema(request=inline_serializer(name="UserConfirmEmailSerializer",
                                             fields={"code": serializers.CharField(required=True,
                                                                                   min_length=6, max_length=6)}),
                   responses=None
                   )
    @action(methods=["POST"], detail=False, url_path="confirm-email",
            parser_classes=[JSONParser],
            authentication_classes=[UserNonRequiredAuthentication])
    def confirm_email(self, request):
        """
        Функция подтверждения почты
        """
        check_captcha(request.data.get("captcha"))
        code = request.data.get("code")
        try:
            confirm_request = ConfirmRequest.objects.get(code=code)
        except:
            return ResponseLocale(user=request.user, status=404, data={"message": "Invalid confirmation token!"})
        if not confirm_request.validate():
            confirm_request.delete()
            return ResponseLocale(user=request.user, status=400, data={"message": "The confirmation link has expired"})
        confirm_request.user.is_active = True
        confirm_request.user.save()
        confirm_request.delete()
        return ResponseLocale(user=request.user, status=200, data={"message": "The email has been confirmed!"})

    @extend_schema(request=inline_serializer("ResetPasswordRequest", fields={
        "email": serializers.EmailField(required=True)
    }),)
    @action(methods=["POST"], detail=False, url_path="reset-password-request",
            authentication_classes=[UserNonRequiredAuthentication])
    def reset_password_send(self, request: Request):
        response = Response(status=200, data={"message": "An email with a reset code has been sent to the post office!"})
        try:
            user = User.objects.get(email=request.data["email"])
        except:
            return response
        # if user.is_active:
        if user.email:
            reset_token = uuid4()
            send_code(user, "Сброс пароля", "сброса пароля",
                      ConfirmRequest.RequestTypes.reset, token=reset_token)
            response.set_cookie("reset_token", reset_token, expires=datetime.timedelta(hours=3))
        return response

    @extend_schema(request=inline_serializer("ResetPasswordEnterCode", fields={
        "code": serializers.CharField(min_length=6, max_length=6)
    }))
    @action(methods=["POST"], detail=False, url_path="reset-password-enter-code",
            authentication_classes=[UserNonRequiredAuthentication])
    def reset_password_enter_code(self, request: Request):
        reset_token = request.COOKIES.get("reset_token")
        try:
            confirm_request = ConfirmRequest.objects.get(token=reset_token,
                                                         type=ConfirmRequest.RequestTypes.reset)
        except:
            return ResponseLocale(user=request.user, status=400, data={"message": "Invalid reset code!"})
        if datetime.datetime.now().timestamp() > (confirm_request.datetime+timedelta(hours=3)).timestamp():
            return ResponseLocale(user=request.user, status=400, data={"message": "Reset code has expired!"})
        if request.data.get("code") != confirm_request.code:
            return ResponseLocale(user=request.user, status=400, data={"message": "Invalid reset code!"})
        confirm_request.type = ConfirmRequest.RequestTypes.password_set
        confirm_request.save()
        return ResponseLocale(user=request.user, status=200, data={"message": "OK!"})


    @extend_schema(request=inline_serializer("ResetPassword", fields={
        "password": serializers.CharField()
    }))
    @action(methods=["POST"], detail=False, url_path="reset-password",
            authentication_classes=[UserNonRequiredAuthentication])
    def reset_password(self, request: Request):
        reset_token = request.COOKIES.get("reset_token")
        password = request.data.get("password")
        try:
            confirm_request = ConfirmRequest.objects.get(token=reset_token,
                                                         type=ConfirmRequest.RequestTypes.password_set)
        except:
            return ResponseLocale(user=request.user, status=400, data={"message": "Reset code has expired!"})
        if datetime.datetime.now().timestamp() > (confirm_request.datetime+timedelta(hours=3)).timestamp():
            return ResponseLocale(user=request.user, status=400, data={"message": "Reset code has expired!"})
        confirm_request.user.password = make_password(password)
        confirm_request.user.save()
        confirm_request.delete()
        tokens = Token.objects.filter(user=confirm_request.user)
        tokens.delete()
        return ResponseLocale(user=request.user, status=200, data={"message": "Password changed successful!"})

    @extend_schema(request=inline_serializer("TopUpBalance", fields={
        "amount": serializers.DecimalField(max_digits=10, decimal_places=2),
        "payment_type": serializers.ChoiceField(choices=PaymentType.choices)
    }))
    @action(methods=["POST"], detail=False, url_path="top-up-balance",
            authentication_classes=[TempUserAuthentication])
    def top_up_balance(self, request):
        payment_type = request.data.get("payment_type")
        if not payment_type:
            payment_type = "cryptomus"
        try:
            amount = float(request.data.get("amount"))
            if amount < 0:
                return ResponseLocale(user=request.user, status=400, data={"message": "No"})
        except:
            return ResponseLocale(user=request.user, status=400, data={"message": "Invalid amount!"})
        invoice_data, uuid = None, None
        if payment_type == PaymentType.stripe:
            invoice_data = stripe_create_invoice(request.user.pk, amount)
            uuid = invoice_data.get("uuid")
        payment = BalanceTopUp(
            uuid=uuid,
            buyer=request.user,
            amount=amount,
            payment_type=payment_type
        )
        payment.save()
        if payment_type in [PaymentType.crypto]:
            if Invoice.objects.filter(
                ~Q(balance_top_up__status=TransactionStatus.paid),
                balance_top_up__buyer_id=request.user.pk,
                is_active=True,
                expiration_dt__gte=datetime.datetime.now()
            ).count() >= 30:
                return ResponseLocale(user=request.user, status=400, data={"message": "You cannot have more than 30 active unpaid invoices!"})
            invoice = Invoice(
                amount_usd=amount,
                balance_top_up=payment,
                type="balance"
            )
            invoice.save()
            return ResponseLocale(user=request.user, status=200, data={"url": f"https://gemups.com/payment/{invoice.uuid}"})
        if payment_type == PaymentType.stripe:
            return ResponseLocale(user=request.user, status=200,
                                  data={"url": invoice_data.get("url")})
        return ResponseLocale(user=request.user, status=200,
                              data={"url": f"https://pay.cryptomus.com/pay/{payment.uuid}"})

    @extend_schema(request=inline_serializer("BecomeSeller", fields={
        "accept_offer": serializers.BooleanField(required=True)
    }))
    @action(methods=["POST"], detail=False, url_path="become-seller",
            authentication_classes=[UserAuthentication])
    def become_seller(self, request: Request):
        if not request.data.get("accept_offer"):
            return ResponseLocale(user=request.user, status=400, data={"message": "You have not accepted the agreement!"})
        if Seller.objects.filter(user_id=request.user.pk).exists():
            return ResponseLocale(user=request.user, status=400, data={"message": "You are already a seller!"})
        if request.user.role not in [User.RoleChoices.admin, User.RoleChoices.root_admin]:
            request.user.role = User.RoleChoices.seller
            request.user.save()
        Seller.objects.create(user=request.user)
        return ResponseLocale(user=request.user, status=200, data={"message": "Now you are a seller!"})

    @extend_schema(request=UserSerializer(partial=True))
    @action(methods=["PATCH"], detail=False, url_path="edit-profile",
            authentication_classes=[TempUserAuthentication])
    def edit_profile(self, request: Request):
        user_serializer = self.serializer_class(instance=request.user, data=request.data, partial=True)
        user_serializer.is_valid(raise_exception=True)
        user_serializer.save()
        return ResponseLocale(user=request.user, status=200, data={"message": "The profile has been updated!"})

    @extend_schema(request=inline_serializer("UploadUserPhoto", fields={
        "photo": serializers.ImageField(),
        "type": serializers.ChoiceField(choices=["banner", "avatar"])
    }))
    @action(methods=["POST"], detail=False, url_path="upload-photo",
            authentication_classes=[TempUserAuthentication], parser_classes=[MultiPartParser])
    def upload_photo(self, request: Request):
        PhotoUploadSerializer(data=request.data).is_valid(raise_exception=True)
        file = request.FILES.get("photo")
        url = upload_file_to_s3(file, f"photos/users/{request.user.pk}")
        photo = File(url=url)
        photo.save()
        if request.data.get("type") == "banner":
            request.user.banner = photo
        else:
            request.user.avatar = photo
        request.user.save()
        return ResponseLocale(user=request.user, status=200, data={"message": "Photo uploaded!", "url": url})

    @extend_schema(parameters=[inline_serializer("DeleteUserPhoto", fields={
        "type": serializers.ChoiceField(choices=["banner", "avatar"])
    })])
    @action(methods=["DELETE"], detail=False, url_path="delete-photo",
            authentication_classes=[TempUserAuthentication])
    def delete_photo(self, request: Request):
        if request.query_params.get("type") == "banner":
            photo = request.user.banner
            request.user.banner = None
        else:
            photo = request.user.avatar
            request.user.avatar = None
        request.user.save()
        if photo:
            photo.delete()
        return ResponseLocale(user=request.user, status=200, data={"message": "Photo deleted!"})

    @action(methods=["GET"], detail=False, url_path="get-referral-balance",
            authentication_classes=[TempUserAuthentication])
    def get_referral_balance(self, request: Request):
        referral_transactions = ReferralTransaction.objects.filter(
            to_user=request.user,
            type=ReferralTransaction.Types.accrual
        )
        hold_transactions = referral_transactions.filter(created_at__gte=datetime.datetime.now()-timedelta(days=3))
        total_amount = round(sum([transaction.amount for transaction in referral_transactions]), 2)
        hold_amount = round(sum([transaction.amount for transaction in hold_transactions]), 2)
        credited_amount = round(total_amount-hold_amount, 2)
        withdraw_transactions = ReferralTransaction.objects.filter(
            to_user=request.user,
            type=ReferralTransaction.Types.withdraw
        )
        withdraw_amount = round(sum([transaction.amount for transaction in withdraw_transactions]), 2)
        available_amount = round(credited_amount-withdraw_amount, 2)
        data = {
            "total": total_amount,
            "hold": hold_amount,
            "credited": credited_amount,
            "available": available_amount,
            "total_users": len(set([transaction.from_user for transaction in referral_transactions])),
        }
        return ResponseLocale(user=request.user, status=200, data=data)

    @extend_schema(parameters=[inline_serializer("GetReferralTransactions", fields={
        "page": serializers.IntegerField(required=False),
        "limit": serializers.IntegerField(required=False),
        "status": serializers.ChoiceField(required=False,
                                          choices=[("accrued", "Начислено"), ("process", "В процессе")])
    })])
    @action(methods=["GET"], detail=False, url_path="get-referral-transactions",
            authentication_classes=[TempUserAuthentication])
    def get_referral_transactions(self, request: Request):
        status = request.query_params.get("status")
        page = request.query_params.get("page")
        limit = request.query_params.get("limit")
        filters = Q()
        if status == "accrued":
            filters &= Q(created_at__lte=datetime.datetime.now()-timedelta(days=3))
        if status == "process":
            filters &= Q(created_at__gte=datetime.datetime.now()-timedelta(days=3))
        referral_transactions = ReferralTransaction.objects.filter(
            filters, to_user=request.user, type=ReferralTransaction.Types.accrual
        )
        data = []
        count = referral_transactions.count()
        if limit and page:
            try:
                limit, page = int(limit), int(page)
            except:
                return ResponseLocale("Invalid parameter - limit or page")
            referral_transactions = referral_transactions[(page-1)*limit:page*limit]
        for referral_transaction in referral_transactions:
            transaction = referral_transaction.transaction
            if not transaction:
                continue
            transaction_data = dict(
                purchase_amount=transaction.amount,
                quantity=transaction.quantity,
                product=dict(title=transaction.product.title,
                             id=transaction.product.pk),
                buyer=dict(username=transaction.buyer.username,
                           id=transaction.buyer.pk),
                seller=dict(id=transaction.seller.pk,
                            name=transaction.seller.user.username),
                created_dt=referral_transaction.created_at,
                referral_amount=referral_transaction.amount,
                status="accrued" if (referral_transaction.created_at+timedelta(days=3)).timestamp() <=
                                    datetime.datetime.now().timestamp() else "process")
            data.append(transaction_data)
        return ResponseLocale(user=request.user, status=200, data={
            "transactions": data,
            "total_pages": ceil(count/limit) if limit and page else None
        })


    @extend_schema(request=inline_serializer("TransferToBalance", fields={
        "amount": serializers.FloatField(),
        "from": serializers.ChoiceField(choices=[("referral", "С реферального счёта"),
                                                 ("seller", "Со счёта продавца")])
    }))
    @action(methods=["POST"], detail=False, url_path="transfer-to-balance",
            authentication_classes=[TempUserAuthentication])
    def transfer_balance(self, request: Request):
        try:
            request.data["amount"] = float(request.data["amount"])
            if request.data["amount"] < 0:
                return ResponseLocale(user=request.user, status=400, data={"message": "No"})
        except:
            return ResponseLocale(user=request.user, status=200, data={"message": "Invalid amount"})
        if request.data.get("from") == "referral":
            return self._transfer_referral_balance(request)
        elif request.data.get("from") == "seller":
            return self._transfer_seller_balance(request)
        return ResponseLocale(user=request.user, status=400, data={"message": "Invalid account type"})

    @staticmethod
    def _transfer_seller_balance(request: Request):
        amount = request.data.get("amount")
        if request.user.role != User.RoleChoices.seller:
            return ResponseLocale(user=request.user, status=403, data={"message": "No"})
        seller = get_object_or_404(Seller, user_id=request.user.pk)
        seller_stat = get_seller_stat(Purchase.objects.filter(seller=seller), seller)
        if seller_stat.get("available_amount") < amount:
            return ResponseLocale(user=request.user, status=400, data={"message": "Insufficient funds!"})
        transfer = Purchase(seller=seller, buyer=seller.user,
                            amount=amount, status="paid",
                            payment_type="balance")
        transfer.save()
        request.user.balance += amount
        request.user.save()
        return ResponseLocale(user=request.user, status=200, data={"message": "The money has been credited to the balance"})

    @staticmethod
    def _transfer_referral_balance(request: Request):
        withdraw_amount = request.data.get("amount")
        accrual_transactions = ReferralTransaction.objects.filter(
            to_user=request.user,
            created_at__lte=datetime.datetime.now()-timedelta(days=3),
            type=ReferralTransaction.Types.accrual
        )
        withdraw_transactions = ReferralTransaction.objects.filter(
            to_user=request.user,
            type=ReferralTransaction.Types.withdraw
        )
        accrual_amount = round(sum([transaction.amount for transaction in accrual_transactions]), 2)
        withdrawn_amount = round(sum([transaction.amount for transaction in withdraw_transactions]), 2)
        referral_balance = round(accrual_amount - withdrawn_amount, 2)
        if referral_balance < withdraw_amount:
            return ResponseLocale(user=request.user, status=400, data={"message": "Insufficient funds!"})
        withdraw_transaction = ReferralTransaction(
            amount=withdraw_amount,
            from_user=request.user,
            to_user=request.user,
            type=ReferralTransaction.Types.withdraw
        )
        withdraw_transaction.save()
        request.user.balance += withdraw_amount
        request.user.save()
        return ResponseLocale(user=request.user, status=200, data={"message": "Money accrued to balance"})

    @action(methods=["POST"], detail=False, url_path="link-tg",
            authentication_classes=[TempUserAuthentication])
    def link_tg(self, request: Request):
        if TgUser.objects.filter(user=request.user).exists():
            return ResponseLocale(user=request.user, status=400, data={"message": "You have already linked a telegram"})
        tg_link = TgLink(uuid=uuid4(), user=request.user)
        tg_link.save()
        return ResponseLocale(user=request.user, status=200, data={"url": f"https://t.me/{BOT_USERNAME}?start={tg_link.uuid}"})

    @action(methods=["POST"], detail=False, url_path="verify-tg",
            authentication_classes=[UserNonRequiredAuthentication])
    def verify_tg(self, request: Request):
        if request.data.get("secret_key") != TG_SECRET_KEY:
            return ResponseLocale(user=request.user, status=403, data={"message": "You don't have access to this resource"})
        tg_link = get_object_or_404(TgLink, uuid=request.data.get("uuid"))
        if TgUser.objects.filter(Q(user=tg_link.user) | Q(telegram_id=request.data.get("id"))).exists():
            return ResponseLocale(user=request.user, status=400, data={"message": "You have already linked a telegram"})
        tg_user = TgUser(telegram_id=request.data.get("id"), user=tg_link.user)
        tg_user.save()
        # gift_proxy_plan(tg_link.user.pk)
        return ResponseLocale(user=request.user, status=200, data={"message": "Telegram successful linked!",
                                          "username": tg_link.user.username})

@extend_schema(tags=["Продавцы"])
class SellerViewSet(GenericViewSet):
    queryset = Seller.objects.all()
    authentication_classes = [UserNonRequiredAuthentication]

    @extend_schema(parameters=[inline_serializer("GetSellerInfo", fields={
        "id": serializers.IntegerField()
    })])
    @action(methods=["GET"], detail=False, url_path="get-info")
    def get_info(self, request: Request):
        try:
            return ResponseLocale(user=request.user, status=200, data=Seller.objects.get(id=request.query_params.get("id")).to_dict())
        except:
            return ResponseLocale(user=request.user, status=404, data={"message": "Seller not found!"})

    @extend_schema(parameters=[inline_serializer("GetSales", fields={
        "page": serializers.IntegerField(required=False),
        "limit": serializers.IntegerField(required=False),
        "statuses": serializers.CharField(required=False)
    })])
    @action(methods=["GET"], detail=False, url_path="get-sales")
    def get_sales(self, request: Request):
        limit = request.query_params.get("limit")
        page = request.query_params.get("page")
        statuses = request.query_params.get("statuses")
        seller = get_object_or_404(Seller, user=request.user)
        filters = Q()
        if statuses:
            filters &= Q(status__in=statuses.split(","))
        purchases = Purchase.objects.filter(filters, ~Q(buyer=request.user), seller=seller)
        count = purchases.count()
        data = []
        if limit and page:
            try:
                limit, page = int(limit), int(page)
            except:
                return ResponseLocale("Invalid parameter - limit or page")
            purchases = purchases[(page-1)*limit:page*limit]
        for purchase in purchases:
            data.append(dict(
                purchase=dict(
                    id=purchase.id, dt=purchase.created_at, amount=purchase.amount,
                    buyer_message=purchase.buyer_message, provided=purchase.provided,
                    quantity=purchase.quantity
                ),
                buyer=dict(id=purchase.buyer.pk,
                           name=purchase.buyer.username),
                product=dict(id=purchase.product.pk,
                             title=purchase.product.title, type=purchase.product.type)
            ))
        return ResponseLocale(user=request.user, status=200, data={
            "total_pages": ceil(count/limit) if limit else None,
            "sales": data,
            "total_sales": count,
            "total_amount": sum([sale.get("purchase").get("amount") for sale in data])
        })

    @extend_schema(parameters=[inline_serializer("GetSellerReviews", fields={
        "id": serializers.IntegerField(),
        "limit": serializers.IntegerField(),
        "page": serializers.IntegerField()
    })])
    @action(methods=["GET"], detail=False, url_path="get-reviews")
    def get_reviews(self, request: Request):
        try:
            limit = int(request.query_params["limit"])
            page = int(request.query_params["page"])
        except (KeyError, ValueError):
            return ResponseLocale(user=request.user, status=400, data={"message": "Missed required parameter - limit or page!"})
        reviews_data = []
        reviews = Review.objects.filter(product__seller__user__id=request.query_params.get("id"))
        for review in reviews[(page-1)*limit:page*limit]:
            data = review.to_dict()
            data["product"] = dict(id=review.product.pk, title=review.product.title)
            reviews_data.append(data)
        return ResponseLocale(user=request.user, status=200, data={"reviews": reviews_data, "total_pages": ceil(reviews.count()/limit)})


    @action(methods=["GET"], detail=False, url_path="get-balance",
            authentication_classes=[SellerAuthentication])
    def get_balance(self, request: Request):
        try:
            seller = get_object_or_404(Seller, user=request.user)
        except:
            return ResponseLocale(user=request.user, status=403, data={"message": "You are not a seller!"})
        transactions = Purchase.objects.filter(status=TransactionStatus.paid, seller=seller)
        seller_stat = get_seller_stat(transactions, seller)
        return ResponseLocale(user=request.user, status=200, data=seller_stat)

    @staticmethod
    def _get_product_data(product, product_type=None):
        reviews = Review.objects.filter(product=product)
        product_data = dict(
            id=product.id,
            title=product.title,
            sold=product.sold,
            total_profit=sum([purchase.amount for purchase in
                              Purchase.objects.filter(product=product, status=TransactionStatus.paid)]),
            in_stock=product.in_stock,
            photo=product.photo.url if product.photo else None,
            prices=[{"price": product.prices.get(amount), "amount": amount} for amount in product.prices],
            description=product.description,
            short_description=product.short_description,
            tags=[tag.to_dict() for tag in product.tags.all()],
            rating=sum([review.rating for review in reviews])/reviews.count() if reviews else 0.0,
            category=dict(id=product.categories.last().pk,
                          title=product.categories.last().name)
        )
        if product_type:
            product_data["type"] = product.type
        return product_data

    @extend_schema(parameters=[inline_serializer("GetMyProducts", fields={
        "type": serializers.ChoiceField(choices=Product.ProductTypes.choices, required=False),
        "limit": serializers.IntegerField(),
        "page": serializers.IntegerField()
    })])
    @action(methods=["GET"], detail=False, url_path="get-my-products",
            authentication_classes=[SellerAuthentication])
    def get_my_products(self, request: Request):
        try:
            limit = int(request.query_params["limit"])
            page = int(request.query_params["page"])
        except:
            return ResponseLocale(user=request.user, status=400, data={"message": "Invalid required parameter - limit or page!"})
        products_type = request.query_params.get("type")
        try:
            seller = Seller.objects.get(user=request.user)
        except:
            return ResponseLocale(user=request.user, status=403, data={"message": "You are not a seller!"})
        if products_type:
            products = Product.objects.filter(type=products_type, seller=seller)
        else:
            products = Product.objects.filter(seller=seller)
        count = products.count()
        products = products[(page-1)*limit:page*limit]
        data = [self._get_product_data(product, products_type) for product in products]
        return ResponseLocale(user=request.user, status=200, data={"products": data,
                                          "total_pages": ceil(count/limit),
                                          "is_verified": seller.is_verified})

    @extend_schema(parameters=[inline_serializer("GetSellerProducts", fields={
        "id": serializers.IntegerField(),
        "limit": serializers.IntegerField(),
        "page": serializers.IntegerField()
    })])
    @action(methods=["GET"], detail=False, url_path="get-products")
    def get_products(self, request: Request):
        try:
            limit = int(request.query_params["limit"])
            page = int(request.query_params["page"])
        except:
            return ResponseLocale(user=request.user, status=400, data={"message": "Invalid required parameter - limit or page!"})
        products = Product.objects.filter(seller__user__id=request.query_params.get("id"))
        count = products.count()
        products_data = []
        for product in products[(page-1)*limit:page*limit]:
            product_data = product.to_dict()
            product_data.pop("seller_info")
            products_data.append(product_data)
        return ResponseLocale(user=request.user, status=200, data={
            "products": products_data,
            "total_pages": ceil(count/limit),
        })

    # Для kyc
    # @extend_schema(request=inline_serializer("ProvideProduct", fields={
    #     "id": serializers.IntegerField(),
    #     "file": serializers.FileField()
    # }))
    # @action(methods=["POST"], detail=False, url_path="provide-product", parser_classes=[MultiPartParser])
    # def provide_product(self, request: Request):
    #     try:
    #         seller = Seller.objects.get(user=request.user)
    #     except:
    #         return ResponseLocale(user=request.user, status=403, data={"message": "Вы не продавец!"})
    #     purchase = get_object_or_404(Purchase, id=request.data.get("id"), seller=seller)
    #     product_data = ProductData(purchase=purchase, product=purchase.product,
    #                                data=request.data.get("data"), is_sold=True)
    #     product_data.save()
    #     purchase.seller_message = request.data.get("data")
    #     purchase.provided = True
    #     purchase.save()
    #     return ResponseLocale(user=request.user, status=200, data={"message": "Товар предоставлен покупателю"})

@extend_schema(tags=["Админы"])
class AdminViewSet(GenericViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    authentication_classes = [AdminAuthentication]
    logger = logging.getLogger("admin_logger")

    def _admin_response(self, request, response):
        request_data = request.data or request.query_params.dict()
        request_str = ""
        for key, value in request_data.items():
            request_str += f"{key}={value}\n"
        if request.path != "/api/v1/admin/get-rows" or request_data.get("model") != "AdminAction":
            admin_action = AdminAction(
                params=request_str,
                response_code=response.status_code,
                user=request.user,
                endpoint=request.path
            )
            admin_action.save()
        self.logger.log(logging.INFO, f"[{request.method}] Request {request.path}\n"
                                      f"Data:\n{request_str}"
                                      f"Response:\n{response.data}\n"
                                      f"UserID: {request.user.pk}")
        return response

    @extend_schema(parameters=[OpenApiParameter(location=OpenApiParameter.COOKIE, name="token")],
                   request=inline_serializer(name="AdminAddSerializer",
                                             fields={"email": serializers.EmailField(required=True),
                                                     "role": serializers.ChoiceField(choices=User.RoleChoices.choices)}))
    @action(methods=["POST"], detail=False, url_path="add",
            parser_classes=[JSONParser])
    def add(self, request: Request):
        email = request.data.get("email")
        role = request.data.get("role")
        try:
            user = User.objects.get(email=email)
        except:
            return ResponseLocale(user=request.user, status=404, data={"message": "There is no user with this email address!"})
        user.role = role
        user.save()
        user.password = make_password(uuid4().hex)
        Token.objects.filter(user=user).delete()
        send_code(user, f"Сброс пароля в связи с выдачей роли {role}")
        return self._admin_response(request, Response(status=200, data={"message": "Admin added!"}))

    @extend_schema(parameters=[OpenApiParameter(location=OpenApiParameter.COOKIE, name="token"),
                               inline_serializer(name="AdminsGetSerializer",
                                                 fields={"limit": serializers.IntegerField(required=False),
                                                         "page": serializers.IntegerField(required=False)},)],
                   responses={200: OpenApiResponse(response=inline_serializer("AdminGet", fields={
                       "username": serializers.CharField(),
                       "email": serializers.EmailField(),
                       "role": serializers.ChoiceField(choices=User.RoleChoices.choices)
                   }))})
    @action(methods=["GET"], detail=False, url_path="get")
    def get(self, request: Request):
        try:
            limit = int(request.query_params.get("limit"))
            page = int(request.query_params.get("page"))
        except:
            return ResponseLocale(user=request.user, status=400, data={"message": "Invalid required parameter - limit or page"})
        admins = User.objects.filter(role__in=["admin", "root-admin"])
        admins = [admin.to_dict() for admin in admins]
        total_pages = ceil(len(admins) / limit)
        admins = admins[(page - 1) * limit:page * limit]
        if not admins:
            return ResponseLocale(user=request.user, status=404, data={"message": f"No admins were found on the {page} page!"})
        return self._admin_response(request, Response(status=200, data={"total_pages": total_pages, "admins": admins}))

    @extend_schema(parameters=[OpenApiParameter(location=OpenApiParameter.COOKIE, name="token", required=False),
                               inline_serializer(name="AdminDeleteSerializer",
                                                 fields={"id": serializers.IntegerField(required=True)})])
    @action(methods=["DELETE"], detail=False, url_path="delete")
    def delete(self, request: Request):
        admin = get_object_or_404(User, id=request.query_params.get("id"))
        admin.role = "user"
        admin.save()
        return self._admin_response(request, Response(status=200, data={"message": "Admin deleted!"}))

    @extend_schema(parameters=[OpenApiParameter(location=OpenApiParameter.COOKIE, name="token")],
                   request=inline_serializer(name="AdminBanSerializer",
                                             fields={"id": serializers.IntegerField(required=True)}))
    @action(methods=["PATCH"], detail=False, url_path="ban",
            parser_classes=[JSONParser])
    def ban(self, request: Request):
        user_id = request.data.get("id")
        try:
            admin = User.objects.get(id=user_id)
        except:
            return ResponseLocale(user=request.user, status=404, data={"message": "There is no admin with this id!"})
        admin.banned = True
        admin.role = User.RoleChoices.user
        admin.password = make_password(f"Ты забанен гад!{uuid4().hex}")
        Token.objects.filter(user=admin).delete()
        admin.save()
        return self._admin_response(request, Response(status=200, data={"message": "Admin banned!"}))

    @staticmethod
    def get_fields_types(model):
        fields_types = {}
        for field in model._meta.fields:
            name = field.name
            if isinstance(field, models.ForeignKey):
                name += "_id"
            fields_types[name] = type(field)
        return fields_types

    @action(methods=["GET"], detail=False, url_path="get-models")
    def get_models(self, request: Request):
        apps_models = {
            "Users": [model.__name__ for model in apps.get_app_config("Users").get_models()],
            "Main": [model.__name__ for model in apps.get_app_config("Main").get_models()],
            "Proxy": [model.__name__ for model in apps.get_app_config("Proxy").get_models()],
        }
        return ResponseLocale(user=request.user, status=200, data=apps_models)

    @extend_schema(parameters=[inline_serializer("GetModelFields", fields={
        "model": serializers.CharField(),
        "category": serializers.CharField()
    })])
    @action(methods=["GET"], detail=False, url_path="get-fields")
    def get_fields(self, request: Request):
        model = apps.get_app_config(request.query_params.get("category")).get_model(request.query_params.get("model"))
        fields_data = []
        fields_types = self.get_fields_types(model)
        for field in fields_types:
            field_type = fields_types.get(field)
            field_data = {"name": field, "type": FieldsTypeSerializer.get_type(field_type)[1]}
            fields_data.append(field_data)
        return ResponseLocale(user=request.user, status=200, data=fields_data)

    @staticmethod
    def _generate_query(query):
        filters = {}
        if not query or "=" not in query:
            return {}
        for condition in query.split("&"):
            condition = (condition.replace("<=", "__lte=").replace(">=", "__gte=")
                         .replace("<", "__lt=").replace(">", "__gt="))
            field_cond = condition.split("=")[0]
            value = condition.split("=")[1]
            if value.startswith("["):
                value = value.replace("[", "").replace("]", "").split(",")
            filters[field_cond] = value
        return filters

    @extend_schema(parameters=[inline_serializer("GetRows", fields={
        "category": serializers.CharField(),
        "model": serializers.CharField(),
        "query": serializers.CharField(required=False),
        "limit": serializers.IntegerField(),
        "page": serializers.IntegerField()
    })])
    @action(methods=["GET"], detail=False, url_path="get-rows")
    def get_rows(self, request: Request):
        try:
            limit = int(request.query_params.get("limit"))
            page = int(request.query_params.get("page"))
        except:
            return ResponseLocale(user=request.user, status=400, data={"message": "Invalid required parameter - limit or page"})
        query = request.query_params.get("query")
        model = apps.get_app_config(request.query_params.get("category")).get_model(request.query_params.get("model"))
        filters = self._generate_query(query)
        if not filters and query:
            filters = Q()
            for field in model._meta.fields:
                first_condition = (hasattr(field, 'get_internal_type')
                                   and field.get_internal_type() in ['CharField', 'TextField'])
                second_condition = (hasattr(field, 'get_internal_type')
                                    and field.get_internal_type() in [
                                        "IntegerField", "BigAutoField",
                                        'CharField', 'TextField'] and query.isdigit())
                if first_condition or second_condition:
                    filters |= Q(**{f"{field.name}__icontains": query})
            data = model.objects.filter(filters)
        else:
            data = model.objects.filter(**filters)
        count = data.count()
        data_list = []
        for row in data[(page - 1) * limit:page * limit]:
            object_data = {}
            for field in model._meta.fields:
                field_name = field.name
                value = row.__dict__.get(field_name)
                if isinstance(field, models.ForeignKey):
                    field_name += "_id"
                    value = row.__dict__.get(field_name)
                    if value:
                        model_name = field.related_model.__name__
                        app_name = field.related_model.__module__.split(".")[0]
                        value = (f"{value}__category={app_name}&model={model_name}"
                                 f"&limit=1&page=1"
                                 f"&query=id={value}")
                object_data[field_name] = value
            data_list.append(object_data)
        return self._admin_response(request, Response(status=200, data={"rows": data_list, "total_elems": count}))

    @extend_schema(request=inline_serializer("AdminUpdateRows", fields={
        "category": serializers.CharField(),
        "model": serializers.CharField(),
        "query": serializers.CharField(required=False),
        "query-actions": serializers.CharField()
    }))
    @action(methods=["PATCH"], detail=False, url_path="update-rows")
    def update_rows(self, request: Request):
        model = apps.get_app_config(request.data.get("category")).get_model(request.data.get("model"))
        fields_types = self.get_fields_types(model)
        filters = self._generate_query(request.data.get("query"))
        objects = model.objects.filter(**filters)
        query_actions = self._generate_query(request.data.get("query-actions"))
        for db_object in objects:
            for field in query_actions:
                if field == "role":
                    request.user, _ = base_authenticate(request, query_actions[field])
                if field == "password":
                    query_actions["password"] = make_password(query_actions["password"])
                db_object.__dict__[field] = FieldsTypeSerializer.get_type(fields_types.get(field))[0](query_actions[field])
            try:
                db_object.save()
            except IntegrityError as db_error:
                error_msg = str(db_error).split("DETAIL:  ")[-1].replace('"', "").strip("\n")
                return ResponseLocale(user=request.user, status=400, data={"message": error_msg})
        return self._admin_response(request, Response(status=200, data={"message": "Objects updated successfully!"}))

    @extend_schema(parameters=[inline_serializer("AdminDeleteRows", fields={
        "category": serializers.CharField(),
        "model": serializers.CharField(),
        "query": serializers.CharField(required=False)
    })])
    @action(methods=["DELETE"], detail=False, url_path="delete-rows")
    def delete_rows(self, request: Request):
        model = apps.get_app_config(request.query_params.get("category")).get_model(request.query_params.get("model"))
        filters = self._generate_query(request.query_params.get("query"))
        objects = model.objects.filter(**filters)
        objects.delete()
        return ResponseLocale(user=request.user, status=200, data={"message": "Objects has been deleted!"})

    @extend_schema(request=inline_serializer("SetBalance", fields={
        "id": serializers.IntegerField(),
        "balance": serializers.FloatField(),
    }))
    @action(methods=["POST"], detail=False, url_path="set-balance")
    def set_balance(self, request: Request):
        user = get_object_or_404(User, id=request.data.get("id"))
        user.balance = float(request.data.get("balance"))
        user.save()
        return ResponseLocale(user=request.user, status=200, data={"message": "The balance is set!"})

    @extend_schema(request=inline_serializer("SetVerifiedSeller", fields={
        "id": serializers.IntegerField()
    }))
    @action(methods=["POST"], detail=False, url_path="set-verified-seller")
    def set_verified_seller(self, request: Request):
        seller = get_object_or_404(Seller, user_id=request.data.get("id"))
        seller.is_verified = True
        seller.save()
        return ResponseLocale(user=request.user, status=200, data={"message": "The seller is now verified!"})

    @extend_schema(request=inline_serializer("AddTags", fields={
        "type": serializers.CharField(),
        "tags": serializers.ListField()
    }))
    @action(methods=["POST"], detail=False, url_path="add-tags")
    def add_tags(self, request: Request):
        try:
            for tag in request.data.get("tags"):
                tag_obj = Tag(name=tag, type=request.data.get("type"))
                tag_obj.save()
        except Exception as e:
            print(e)
            return ResponseLocale(user=request.user, status=400, data={"message": "Tag creation error"})
        return ResponseLocale(user=request.user, status=200, data={"message": "Tags created!"})

    @extend_schema(request=inline_serializer("DeleteTags", fields={
        "tag": serializers.CharField()
    }))
    @action(methods=["DELETE"], detail=False, url_path="delete-tag")
    def delete_tag(self, request: Request):
        get_object_or_404(Tag, name=request.query_params.get("tag")).delete()
        return ResponseLocale(user=request.user, status=200, data={"message": "Tag deleted!"})

    @extend_schema(request=inline_serializer("AddCategory", fields={
        "type": serializers.ChoiceField(choices=Product.ProductTypes.choices),
        "name": serializers.CharField(),
        "description": serializers.CharField()
    }))
    @action(methods=["POST"], detail=False, url_path="add-category")
    def add_category(self, request: Request):
        category_serializer = CategorySerializer(data=request.data)
        category_serializer.is_valid(raise_exception=True)
        category_serializer.create(category_serializer.validated_data)
        return ResponseLocale(user=request.user, status=200, data={"message": "Category created!"})

    @extend_schema(request=inline_serializer("VerifySeller", fields={
        "id": serializers.IntegerField()
    }))
    @action(methods=["POST"], detail=False, url_path="verify-seller")
    def seller_verification(self, request: Request):
        seller = get_object_or_404(Seller, id=request.data.get("id"))
        if not seller.user.is_active:
            return ResponseLocale(user=request.user, status=400, data={"message": "The user did not confirm the email!"})
        seller.is_verified = True
        seller.save()
        return ResponseLocale(user=request.user, status=200, data={"message": "The seller is verified!"})
