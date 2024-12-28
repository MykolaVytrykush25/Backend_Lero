import base64
import decimal
import hashlib
import hmac
import json
from datetime import datetime
from uuid import uuid4

from django.db import models

import boto3
from botocore.config import Config
from cryptomus import Client
import stripe
import requests

from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.core.exceptions import ValidationError as DjangoValidationError

from Users.models import User
from inshop.settings import FRONTEND_HOST, CRYPTOMUS_API_KEY, \
    CRYPTOMUS_MERCHANT, PAYMENT_LIFE_TIME, S3_API_KEY, S3_SECRET_KEY, S3_ENDPOINT, S3_BUCKET, \
    S3_ACCESS_KEY, GEETEST_VALIDATE_URL, GEETEST_CAPTCHA_KEY, GEETEST_CAPTCHA_ID, CAPTCHA_ENABLED, \
    STRIPE_SECRET_ENDPOINT, STRIPE_API_KEY
from os import environ

from django.shortcuts import get_object_or_404 as _get_object_or_404
from rest_framework.exceptions import NotFound


environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

s3 = boto3.client('s3', config=Config(signature_version='s3v4'),
                  aws_access_key_id=S3_API_KEY,
                  aws_secret_access_key=S3_SECRET_KEY,
                  endpoint_url=S3_ENDPOINT)


stripe.api_key = STRIPE_API_KEY
client = Client.payment(CRYPTOMUS_API_KEY, CRYPTOMUS_MERCHANT)
with open("static/locales.json", "r", encoding="utf-8") as file:
    locales = json.load(file)


def cryptomus_create_invoice(buyer_id, amount):
    data = {
        'amount': str(float(amount)),
        "currency": "USD",
        'order_id': f"{buyer_id}_{uuid4()}",
        'url_return': f'{FRONTEND_HOST}/payment-success',
        'url_callback': f'{FRONTEND_HOST}/api/v1/payment/cryptomus',
        'is_payment_multiple': False,
        'lifetime': int(PAYMENT_LIFE_TIME)
    }
    return client.create(data)

def stripe_create_invoice(buyer_id, amount):
    user = User.objects.get(id=buyer_id)
    invoice_uuid = str(uuid4())
    customer = stripe.Customer.create(
        name=user.username,
        email=user.email
    )
    # invoices = stripe.Invoice.list(customer=customer.id, status='draft')
    # for draft_invoice in invoices.data:
    #     stripe.Invoice.delete(draft_invoice.id)
    stripe.InvoiceItem.create(
        customer=customer.id,
        amount=int(amount * 100),
        currency="usd",
        description="Proxy from Gemups"
    )
    invoice = stripe.Invoice.create(
        customer=customer.id,
        auto_advance=True,
        pending_invoice_items_behavior="include",
        metadata={"uuid": invoice_uuid},
    )
    invoice = stripe.Invoice.finalize_invoice(invoice.id)
    return dict(url=invoice.hosted_invoice_url, uuid=invoice_uuid)


def stripe_get_event(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    try:
        return stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_SECRET_ENDPOINT
        )
    except ValueError:
        raise ValidationError({"message": "Invalid paylod"})
    except stripe.error.SignatureVerificationError:
        raise ValidationError({"message": "Invalid Signature"})


def stripe_get_invoice(uuid):
    invoice = stripe.Invoice.search(query=f'metadata["uuid"]:"{uuid}"')
    return invoice.data[0].hosted_invoice_url


def get_object_or_404(queryset, *filter_args, **filter_kwargs):
    try:
        return _get_object_or_404(queryset, *filter_args, **filter_kwargs)
    except (TypeError, ValueError, DjangoValidationError):
        raise NotFound(detail={"message": f"{queryset.model.__name__} not found!"})

def check_sign(request_body, key=CRYPTOMUS_API_KEY):
    data = request_body.copy()
    sign = data.get("sign")
    data.pop('sign', None)
    json_data = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('/', '\\/')
    hash_string = base64.b64encode(json_data.encode('utf-8')).decode('utf-8') + key
    generated_hash = hashlib.md5(hash_string.encode('utf-8')).hexdigest()
    return generated_hash == sign

def upload_file_to_s3(file, file_path):
    """
    Method for upload file to S3.
    """
    print(file.content_type)
    if (file.content_type.split("/")[0] not in ["image", "video", "document", "text"] and
            file.content_type != 'application/octet-stream'):
        raise ValidationError(detail={"message": "Invalid file type"})

    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)
    if file_size > 30 * 1024 * 1024:
        raise ValidationError(detail={"message": "The file is too large. Max size - 30 МБ"})
    try:
        bucket = S3_BUCKET
        existing_folders = s3.list_objects(Bucket=bucket, Prefix=f'{file_path}/')
        if 'Contents' not in existing_folders:
            s3.put_object(Bucket=bucket, Key=f'{file_path}/')
        extension = file.content_type.split("/")[1]
        if file.content_type == "text/plain":
            extension = "txt"
        file_name = f"{file_path}/{uuid4()}.{extension}"
        s3.upload_fileobj(file.file, bucket, file_name)
        path = f"{S3_ENDPOINT}/{S3_ACCESS_KEY}:{bucket}/{file_name}"
        return path
    except Exception as error:
        raise error


def delete_file_from_s3(url):
    """
    Method for delete file from S3.
    """
    file_path = url.replace(f"{S3_ENDPOINT}/{S3_BUCKET}/", "")
    file_name = file_path.split("/")[-1]
    folder_path = file_path.replace(file_name, "")
    s3.delete_object(Bucket=S3_BUCKET, Key=file_path)
    files = s3.list_objects(Bucket=S3_BUCKET, Prefix=f"{folder_path}/")
    if "Contents" not in files:
        s3.delete_object(Bucket=S3_BUCKET, Key=folder_path)

credentials = json.load(open("static/crypto.json", "r"))


def get_wallets_and_contracts_by_network(ticker: str, network):
    for entry in credentials:
        if entry["ticker"].lower() == ticker.lower():
            for address_info in entry["providers"]:
                if network.lower() == address_info["network"].lower():
                    return address_info["to_address"][0]

def get_all_crypto_methods():
    data = []
    for entry in credentials:
        currency_data = {"currency": entry.get("ticker"), "networks": []}
        for provider in entry.get("providers"):
            currency_data["networks"].append(provider["network"])
        data.append(currency_data)
    return data


def check_captcha(captcha_data):
    """
    Validate captcha with GeeTest API.
    """
    if not CAPTCHA_ENABLED:
        return
    if not captcha_data:
        raise ValidationError(detail={"message": "Captcha is not provided"})
    lot_number = captcha_data.get("lot_number")
    lot_number_bytes = lot_number.encode()
    private_key_bytes = GEETEST_CAPTCHA_KEY.encode()
    sign_token = hmac.new(private_key_bytes, lot_number_bytes, digestmod='SHA256').hexdigest()
    query = {
        "lot_number": lot_number,
        "captcha_output": captcha_data.get("captcha_output"),
        "pass_token": captcha_data.get("pass_token"),
        "gen_time": captcha_data.get("gen_time"),
        "sign_token": sign_token,
    }
    url = f'{GEETEST_VALIDATE_URL}?captcha_id={GEETEST_CAPTCHA_ID}'
    try:
        res = requests.post(url, query)
        if res.status_code != 200:
            raise ValidationError(detail={"message": "GeeTest Captcha Failed"})
        return
    except:
        return

class FieldsTypeSerializer:
    fields_types_map = {
        models.BooleanField: (bool, "bool"),
        models.IntegerField: (int, "integer"),
        models.FloatField: (float, "float"),
        models.DecimalField: (decimal, "decimal"),
        models.ForeignKey: (int, "FK"),
        models.DateTimeField: (datetime, "datetime"),
        models.JSONField: (json.loads, "json"),
        models.BigAutoField: (int, "integer"),
        models.BigIntegerField: (int, "integer"),
    }

    @classmethod
    def get_type(cls, field):
        return cls.fields_types_map.get(field, (str, "string"))


class ResponseLocale(Response):
    def __init__(self, data=None, status=None,
                 template_name=None, headers=None,
                 exception=False, content_type=None, user=None):
        super().__init__(data, status, template_name, headers, exception, content_type)
        if user:
            if "message" in data:
                if user.locale != 'en' and status in [200, 400, 403]:
                    original_message = data["message"]
                    translations = locales.get(original_message, {})
                    translated_message = translations.get(user.locale, original_message)
                    self.data["message"] = translated_message
