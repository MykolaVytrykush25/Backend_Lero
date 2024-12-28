import datetime

from decimal import Decimal
from math import ceil
from uuid import uuid4

import requests
from django.db.models import Q, Count
from django.http import FileResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect

from drf_spectacular.utils import extend_schema, inline_serializer

from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet

from Main.celery import app

from Main.models import Product, Purchase, Category, TransactionStatus, BalanceTopUp, PaymentType, UserCart, Tag, Units, \
    Review, File, Invoice, ProductData
from Main.serializers import PurchaseSerializer, GetCardsSerializer, ProductSerializer, PhotoUploadSerializer, \
    CryptomusPaymentSerializer
from Main.utils import get_object_or_404, cryptomus_create_invoice, check_sign, upload_file_to_s3, \
    get_all_crypto_methods, get_wallets_and_contracts_by_network, stripe_create_invoice, stripe_get_event, \
    stripe_get_invoice, ResponseLocale

from Proxy.models import ProxyPurchase, ProxyTypes
from Proxy.providers import ProvidersFactory, lola_isp_countries
from Users.models import User, Seller
from Users.utils import TempUserAuthentication, base_authenticate, SellerAuthentication, get_user, \
    UserNonRequiredAuthentication

from inshop.settings import CRYPTO_SECRET_KEY


@extend_schema(tags=["Товары"])
class ProductsViewSet(GenericViewSet):
    queryset = Product.objects.all()
    authentication_classes = [UserNonRequiredAuthentication]
    serializer_class = ProductSerializer

    @staticmethod
    def _buy_proxy(user, product, purchase, quantity):
        proxy_type = product.categories.last()
        extend_of = None
        if proxy_type.name != ProxyTypes.ISP:
            old_proxy_purchase = ProxyPurchase.objects.filter(
                purchase__buyer=user,
                purchase__seller=product.seller,
                type__name=proxy_type.name
            ).exclude(status=ProxyPurchase.ProxyPurchaseStatus.EXPIRED).exclude(service_data={}).last()
            if old_proxy_purchase:
                if old_proxy_purchase.expiration_date.timestamp() < datetime.datetime.now().timestamp():
                    old_proxy_purchase.status = ProxyPurchase.ProxyPurchaseStatus.EXPIRED
                    old_proxy_purchase.save()
                else:
                    extend_of = old_proxy_purchase
        country = None
        if proxy_type.name == ProxyTypes.ISP:
            country = purchase.product_options.get("country")
        proxy_purchase = ProxyPurchase(
            purchase=purchase, type=proxy_type,
            count=quantity,
            extend_of=extend_of,
            country=country
        )
        proxy_purchase.save()
        return proxy_purchase

    def _buy(self, request, user, response, multiple):
        product_id = request.data.get("id")
        quantity = request.data.get('quantity')
        options = request.data.get("options")
        payment_type = request.data.get("payment_type")
        products = request.data.get("products")
        products_objects = []
        products_options = []
        purchase_uuid = None
        price = 0
        if payment_type == PaymentType.crypto:
            if Invoice.objects.filter(
                ~Q(purchases__status=TransactionStatus.paid),
                purchases__buyer_id=user.pk,
                is_active=True,
                expiration_dt__gte=datetime.datetime.now()
            ).count() >= 30:
                return ResponseLocale(user=request.user, status=400, data={"message": "You cannot have more than 30 active unpaid invoices!"})
        if multiple:
            for product in products:
                product_obj = get_object_or_404(Product, id=product.get("id"))
                if product.seller.user.pk == user.pk:
                    return ResponseLocale(user=request.user, status=400, data={"message": "You can't buy from yourself!"})
                if not product_obj.seller.is_verified and user.role not in ["admin", "root_admin"]:
                    raise ValidationError({"message": "Purchase is prohibited!"})
                if product_obj.in_stock is not None and product.in_stock <= 0:
                    raise ValidationError({"message": "Out of stock!"})
                products_objects.append(product_obj)
                products_options.append(product.get("options"))
                quantity = int(product.get("quantity"))
                price += product_obj.get_price(quantity)*quantity
            purchase_uuid = uuid4()
            if payment_type == PaymentType.cryptomus:
                purchase_uuid = cryptomus_create_invoice(user.pk, price).get("uuid")
            if payment_type == PaymentType.stripe:
                invoice_data = stripe_create_invoice(user.pk, price)
                purchase_uuid = invoice_data.get("uuid")
            elif payment_type == PaymentType.balance:
                if user.balance < price:
                    return ResponseLocale(user=request.user, status=400, data={"message": "Insufficient balance!"})
        else:
            product_obj = get_object_or_404(Product, id=product_id)
            products_objects = [product_obj]
            products_options = [options]
        i = 0
        purchases = []
        for product in products_objects:
            if not product.seller.is_verified and user.role not in ["admin", "root_admin"]:
                raise ValidationError({"message": "Purchase is prohibited!"})
            if product.in_stock is not None and product.in_stock <= 0:
                raise ValidationError({"message": "Out of stock!"})
            if not multiple:
                price = product.get_price(quantity)*quantity
                purchase_uuid = uuid4()
                if payment_type == PaymentType.cryptomus:
                    invoice_data = cryptomus_create_invoice(user.pk, price)
                    purchase_uuid = invoice_data.get("uuid")
                if payment_type == PaymentType.stripe:
                    invoice_data = stripe_create_invoice(user.pk, price)
                    purchase_uuid = invoice_data.get("uuid")
            purchase = Purchase(
                product=product, amount=price,
                seller=product.seller, buyer=user,
                payment_type=payment_type, uuid=purchase_uuid,
                buyer_message=request.data.get("buyer-message"),
                product_options=products_options[i], quantity=quantity
            )
            try:
                purchase.save()
                purchases.append(purchase)
            except ValidationError as e:
                response.status_code = 400
                response.data = e.detail
                return response
            if product.type == Product.ProductTypes.proxy:
                self._buy_proxy(user, product, purchase, quantity)
            if payment_type == PaymentType.balance:
                purchase.process()
            i += 1
        response.status_code = 200
        if payment_type == PaymentType.cryptomus:
            response.data = {"url": f"https://pay.cryptomus.com/pay/{purchase_uuid}"}
        if payment_type == PaymentType.stripe:
            response.data = {"url": invoice_data["url"]}
        if payment_type == PaymentType.balance:
            response.data = {"message": "Successful purchase!"}
        if payment_type == "crypto":
            invoice = Invoice(
                amount_usd=price,
            )
            invoice.save()
            invoice.purchases.set(purchases)
            invoice.save()
            response.data = {"url": f"https://gemups.com/payment/{invoice.uuid}"}
        if products:
            for product in products:
                user_cart = UserCart.objects.filter(user=user, product_id=product.get("id")).first()
                if user_cart:
                    user_cart.amount -= int(product.get("quantity"))
                    if user_cart.amount <= 0:
                        user_cart.delete()
                    user_cart.save()
        else:
            user_cart = UserCart.objects.filter(user=user, product_id=product_id).first()
            if user_cart:
                user_cart.amount -= quantity
                user_cart.save()
        cookies = response.cookies
        response = ResponseLocale(data=response.data, user=user, status=response.status_code)
        response.cookies = cookies
        return response

    @extend_schema(request=inline_serializer("ProductBuy", fields={
        "id": serializers.IntegerField(default=1, required=False),
        "quantity": serializers.IntegerField(default=1, required=False),
        "payment_type": serializers.ChoiceField(choices=PaymentType.choices),
        "products": serializers.ListField(child=serializers.JSONField(
            default={"id": 1, "quantity": 1,
                     "options": {
                         "country": "pol",
                         "buyer-message": "message"
                     }})),
        "options": serializers.JSONField(required=False)
    }))
    @action(methods=["POST"], detail=False, url_path="buy")
    def buy(self, request):
        user, response = get_user(request)
        PurchaseSerializer(data=request.data).is_valid(raise_exception=True)
        return self._buy(request, user, response, True if request.data.get("products") else False)

    @extend_schema(parameters=[inline_serializer("GetProducts", fields={
        "type": serializers.ChoiceField(choices=Product.ProductTypes.choices, required=False),
        "category": serializers.CharField(required=False),
        "tags": serializers.CharField(default="1,2,3", required=False),
    })])
    @action(methods=["GET"], detail=False, url_path="get-cards")
    def get_cards(self, request: Request):
        user, _ = base_authenticate(request, "temp_user", False)
        GetCardsSerializer(data=request.query_params).is_valid(raise_exception=True)

        category_name, type, tags = (
            request.query_params.get("category"),
            request.query_params.get("type"),
            request.query_params.get("tags").split(",") if request.query_params.get("tags") else None
        )

        filters = self._build_filters(user, category_name, type)
        products = self._get_filtered_products(tags, filters)
        processed_products, data = [], {}

        if category_name:
            data = self._process_products_by_category(products, processed_products)
        elif type:
            data = self._process_products_by_type(products, processed_products)
        else:
            data = self._process_products_by_type_and_category(products, processed_products)
        return ResponseLocale(user=request.user, status=200, data=data)

    def _build_filters(self, user, category_name, type):
        filters = []
        if not user or user.role not in [User.RoleChoices.admin, User.RoleChoices.root_admin]:
            filters.append(Q(seller__is_verified=True))
        if category_name:
            filters.append(Q(categories__name=category_name) | Q(categories__parent_category__name=category_name))
        if type:
            filters.append(Q(type=type))
        return filters

    def _get_filtered_products(self, tags, filters):
        if tags:
            return Product.objects.filter(tags__id__in=tags, *filters) \
                .annotate(num_tags=Count('tags')) \
                .filter(num_tags=len(tags)).order_by("id").order_by("-is_popular")
        return Product.objects.filter(*filters).order_by("id").order_by("-is_popular")

    def _process_products_by_category(self, products, processed_products):
        data = []
        for product in products:
            if product.pk in processed_products:
                continue
            product_data, skip = self._process_product_and_similars(product, products, processed_products)
            if not skip:
                product_data.pop("category")
                data.append(product_data)
        return data

    def _process_products_by_type(self, products, processed_products):
        data = {}
        for product in products:
            if product.pk in processed_products:
                continue
            product_data, skip = self._process_product_and_similars(product, products, processed_products)
            if not skip:
                category = product.categories.last()
                if not category:
                    continue
                data.setdefault(category.name, []).append(product_data)
        if products[0].type == Product.ProductTypes.proxy:
            sorted_data = dict()
            for category in ["residential", "datacenter", "isp"]:
                if category in data:
                    sorted_data[category] = data[category]
        else:
            sorted_data = dict(sorted(data.items(), key=lambda item: len(item[1]), reverse=False))
        return sorted_data

    def _process_products_by_type_and_category(self, products, processed_products):
        data = {}
        for product in products:
            if product.pk in processed_products:
                continue
            product_data, skip = self._process_product_and_similars(product, products, processed_products)
            if not skip:
                category = "Undefined Category"
                product_category = product.categories.last()
                if product_category:
                    category = product_category.name
                type = product.type
                data.setdefault(type, {}).setdefault(category, []).append(product_data)

        sorted_data = {
            type_: dict(sorted(categories.items(), key=lambda item: len(item[1]), reverse=False))
            for type_, categories in data.items()
        }
        sorted_data = dict(
            sorted(sorted_data.items(), key=lambda item: sum(len(cat) for cat in item[1].values()), reverse=False))
        return sorted_data

    def _process_product_and_similars(self, product, products, processed_products):
        product_data = product.to_dict()
        skip = False
        target_tags = product.tags.all()
        similar_products = []
        if target_tags:
            similar_products = self._get_similar_products(product)
        for similar_product in similar_products:
            similar_rating = self._get_average_rating(similar_product)
            if product_data.get("rating") >= similar_rating and not similar_product.is_popular:
                processed_products.append(similar_product.pk)
                product_data.setdefault("other_sellers", 0)
                product_data.setdefault("other_sellers_avatars", [])
                product_data["other_sellers"] += 1
                if similar_product.seller.user.avatar:
                    if len(product_data["other_sellers_avatars"]) < 3:
                        product_data["other_sellers_avatars"].append(similar_product.seller.user.avatar.url)
            else:
                processed_products.append(product.pk)
                skip = True

        return product_data, skip

    def _get_average_rating(self, product):
        reviews = Review.objects.filter(product_id=product.pk)
        return sum(review.rating for review in reviews) / reviews.count() if reviews else 0.0

    @extend_schema(parameters=[inline_serializer("GetCategories", fields={
        "type": serializers.ChoiceField(choices=Product.ProductTypes.choices, required=False),
    })])
    @action(methods=["GET"], detail=False, url_path="get-categories")
    def get_categories(self, request: Request):
        filters = []
        if request.query_params.get("type"):
            filters.append(Q(type=request.query_params.get("type")))
        return ResponseLocale(user=request.user, status=200, data=[category.to_dict() for category in Category.objects.filter(*filters)])

    @extend_schema(parameters=[inline_serializer("GetTags", fields={
        "type": serializers.ChoiceField(choices=Product.ProductTypes.choices, required=True),
    })])
    @action(methods=["GET"], detail=False, url_path="get-tags")
    def get_tags(self, request: Request):
        return ResponseLocale(user=request.user, status=200, data=[tag.to_dict() for tag in Tag.objects.filter(
            type=request.query_params.get("type")
        )])

    @extend_schema(parameters=[inline_serializer("GetMyProducts", fields={
        "limit": serializers.IntegerField(),
        "page": serializers.IntegerField(),
        "type": serializers.ChoiceField(choices=Product.ProductTypes.choices, required=False),
        "statuses": serializers.CharField(),
        "category": serializers.IntegerField(required=False)
    })])
    @action(methods=["GET"], detail=False, url_path="get-my", authentication_classes=[TempUserAuthentication])
    def get_my(self, request: Request):
        try:
            limit = int(request.query_params["limit"])
            page = int(request.query_params["page"])
        except (KeyError, ValueError):
            return ResponseLocale(user=request.user, status=400, data={"message": "Missed required parameters - limit or page!"})
        product_type = request.query_params.get("type")
        statuses = request.query_params.get("statuses")
        category = request.query_params.get("category")
        filters = [Q(buyer=request.user)]
        if product_type:
            filters.append(Q(product__type=product_type))
        if statuses:
            filters.append(Q(status__in=statuses.split(",")))
        if category:
            filters.append(Q(product__categories__id=category))
        seller = Seller.objects.filter(user=request.user).first()
        if seller:
            filters.append(~Q(seller=seller))
        purchases = Purchase.objects.filter(*filters).order_by("-created_at")
        start = (page - 1) * limit
        end = start + limit
        data = []
        i = 0
        for purchase in purchases:
            try:
                purchase_data = {}
                quantity = None
                expiration_date = None
                country = None
                if purchase.product.type == Product.ProductTypes.proxy:
                    try:
                        proxy_purchase = ProxyPurchase.objects.get(~Q(service_data={}),
                                                                   extend_of_id__isnull=True,
                                                                   purchase=purchase)
                        quantity = {
                            "all": proxy_purchase.count,
                            "is_static": True
                        }
                        if proxy_purchase.extend_of:
                            continue
                        proxy_data = ProvidersFactory.get_provider(proxy_purchase.purchase.seller.user.username)(
                            proxy_purchase)
                        expiration_date = proxy_purchase.expiration_date.strftime("%Y-%m-%d %H:%M:%S")
                        if proxy_purchase.type.name != ProxyTypes.ISP:
                            try:
                                quantity = {
                                    "all": proxy_purchase.count,
                                    "left": proxy_data.get_traffic_left(),
                                    "is_static": False
                                }
                            except:
                                pass
                        if proxy_purchase.country:
                            country = proxy_purchase.country
                    except ProxyPurchase.DoesNotExist:
                        if statuses == "paid":
                            continue
                if start <= i < end:
                    if not quantity:
                        quantity = {"all": purchase.quantity, "is_static": True}
                    product_category = purchase.product.categories.first()
                    invoice = None
                    if purchase.payment_type == PaymentType.cryptomus:
                        invoice = f"https://pay.cryptomus.com/pay/{purchase.uuid}"
                    if purchase.payment_type == PaymentType.crypto:
                        invoice = f"https://gemups.com/payment/{purchase.uuid}"
                    try:
                        if purchase.payment_type == PaymentType.stripe:
                            invoice = stripe_get_invoice(purchase.uuid)
                    except:
                        pass
                    if purchase.status != TransactionStatus.paid:
                        if purchase.created_at.timestamp() < (datetime.datetime.now() - datetime.timedelta(hours=12)).timestamp():
                            purchase.status = TransactionStatus.cancel
                            purchase.save()
                    product_data = {
                        "purchase": {
                            "id": purchase.pk,
                            "datetime": purchase.created_at,
                            "status": purchase.status,
                            "quantity": quantity,
                            "data": purchase.seller_message,
                            "invoice": invoice
                        },
                        "seller": {
                            "name": purchase.seller.user.username,
                            "id": purchase.seller.pk
                        },
                        "product": {
                            "id": purchase.product.pk,
                            "title": purchase.product.title,
                            "type": purchase.product.type,
                            "expiration_date": expiration_date
                        }
                    }
                    if product_category:
                        product_data["product"]["category"] = product_category.name
                        product_data["product"]["category_id"] = product_category.pk
                    purchase_data.update(product_data)
                    if country:
                        purchase_data["purchase"]["country"] = lola_isp_countries[country]
                    purchase_data["purchase"]["quantity"]["unit"] = Units.get_unit(purchase.product)
                    data.append(purchase_data)
                i += 1
            except:
                pass
        total_pages = ceil(i / limit)
        return ResponseLocale(user=request.user, status=200, data={"products": data, "total_pages": total_pages})

    @extend_schema(parameters=[inline_serializer("GetProductData", fields={
        "id": serializers.IntegerField()
    })])
    @action(methods=["GET"], detail=False, url_path="get-product-data",
            authentication_classes=[TempUserAuthentication])
    def get_product_data(self, request: Request):
        purchase = get_object_or_404(Purchase, id=request.query_params.get("id"), buyer=request.user)
        product_data = ProductData.objects.filter(purchase=purchase)
        first_line = True
        file_data = ""
        for piece in product_data:
            if first_line:
                file_data += piece.data
            else:
                file_data += "\n" + piece.data
            first_line = False
        response = FileResponse(file_data, filename=f"{uuid4()}.txt", content_type="text/plain", as_attachment=True)
        response['Content-Disposition'] = f'attachment; filename="purchase_{purchase.pk}.txt"'
        return response

    @staticmethod
    def _get_similar_products(product):
        tags = product.tags.all()
        similar_products = (
            Product.objects
            .filter(categories__in=product.categories.all())
            .filter(tags__in=tags)
            .exclude(id=product.pk)
            .annotate(common_tags=Count('tags'))
            .order_by('-common_tags')
        )
        return similar_products


    @extend_schema(parameters=[inline_serializer("ProductGet", fields={
        "id": serializers.IntegerField()
    })])
    @action(methods=["GET"], detail=False, url_path="get", authentication_classes=[])
    def get(self, request: Request):
        user, _ = base_authenticate(request, "temp_user", False)
        product_id = request.query_params.get("id")
        product = get_object_or_404(Product, id=product_id)
        target_tags = product.tags.all()
        data = {"type": product.type}
        other_offers = None
        if target_tags:
            other_products = self._get_similar_products(product)
            if not user or user.role not in [User.RoleChoices.admin.value,
                                                             User.RoleChoices.root_admin.value]:
                other_products = other_products.exclude(seller__is_verified=False)
            if other_products:
                offers = [dict(
                    seller_info=dict(
                        id=other_product.seller.pk, name=other_product.seller.user.username,
                        photo=other_product.seller.user.avatar.url if other_product.seller.user.avatar else None
                    ),
                    product=dict(id=other_product.pk,
                                 short_description=other_product.short_description,
                                 title=other_product.title, price=other_product.prices.get("1"),
                                 in_stock=other_product.in_stock,
                                 type=other_product.type,
                                 photo=other_product.photo.url if other_product.photo else None),
                ) for other_product in other_products]
                other_offers = {
                    "min_price": min([other_product.prices.get("1") for other_product in other_products]),
                    "offers": offers
                }
        data.update(product.to_dict(user))
        if other_offers:
            data.update({"other_offers": other_offers})
        return ResponseLocale(user=request.user, status=200, data=data)

    @extend_schema(request=inline_serializer("AddToCart", fields={
        "product_id": serializers.IntegerField(),
        "amount": serializers.IntegerField(required=False),
        "operation": serializers.ChoiceField(choices=[
            ("+", "Прибавить"),
            ("-", "Убавить"),
            ("=", "Установить")
        ]),
        "options": serializers.JSONField()
    }))
    @action(methods=["POST"], detail=False, url_path="add-to-cart")
    def add_to_cart(self, request: Request):
        user, response = get_user(request)
        cart = UserCart(user=user, amount=request.data.get("amount"),
                        product=get_object_or_404(
                            Product, id=request.data.get("product_id"),
                        ),
                        options=request.data.get("options"))
        cart.set_amount(request.data.get("operation"))
        in_cart = UserCart.objects.filter(user_id=user.pk).count()
        cookies = response.cookies
        response = ResponseLocale(data={"message": "The product has been added to the cart", "in_cart": in_cart},
                                  user=user, status=200)
        response.cookies = cookies
        return response

    @action(methods=["GET"], detail=False, url_path="get-cart")
    def get_cart(self, request: Request):
        user, _ = base_authenticate(request, "temp_user", False)
        if not user:
            return ResponseLocale(user=request.user, status=200, data=[])
        return ResponseLocale(user=request.user, status=200,
                        data=[product_cart.to_dict() for product_cart in UserCart.objects.filter(user=user)])

    @extend_schema(request=ProductSerializer)
    @action(methods=["POST"], detail=False, url_path="create", authentication_classes=[SellerAuthentication])
    def add(self, request: Request):
        data = request.data
        try:
            data["seller"] = get_object_or_404(Seller, user_id=request.user.pk).pk
        except:
            return ResponseLocale(user=request.user, status=403, data={"message": "You are not a seller!"})
        product_serializer = self.serializer_class(data=data)
        product_serializer.is_valid(raise_exception=True)
        product = product_serializer.create(product_serializer.validated_data)
        return ResponseLocale(user=request.user, status=200, data={"message": "Product created!", "id": product.pk})

    @extend_schema(request=inline_serializer("AddProductData", fields={
        "file": serializers.FileField(required=False),
        "text": serializers.CharField(required=False),
        "id": serializers.IntegerField()
    }))
    @action(methods=["POST"], detail=False, url_path="add-data",
            authentication_classes=[SellerAuthentication], parser_classes=[MultiPartParser])
    def add_data(self, request: Request):
        product = Product.objects.filter(id=request.data.get("id"), seller__user=request.user).first()
        if not product:
            return ResponseLocale(user=request.user, status=400, data={"message": "The product does not exist or you are not its owner!"})
        if product.type not in [Product.ProductTypes.account, Product.ProductTypes.soft]:
            return ResponseLocale(user=request.user, status=400, data={"message": "Uploading data for this type of product is prohibited!"})
        file = request.FILES.get("file")
        if file:
            if file.content_type != "text/plain":
                return ResponseLocale(user=request.user, status=400, data={"message": "Incorrect format, please upload a txt file!"})
            app.send_task(name="add_product_data",
                          route_name="add_product_data",
                          kwargs={
                              "product_id": request.data.get("id"),
                              "text": file.read().decode("utf-8")
                          })
        else:
            text = request.data.get("text")
            if not text:
                return ResponseLocale(user=request.user, status=400, data={"message": "Empty text value!"})
            app.send_task(name="add_product_data",
                          route_name="add_product_data",
                          kwargs={
                              "product_id": request.data.get("id"),
                              "text": text
                          })
        return ResponseLocale(user=request.user, status=200, data={"message": "The data is being uploaded"})

    # @action(methods=["DELETE"], detail=False, url_path="delete",
    #         authentication_classes=[SellerAuthentication])
    # def delete(self, request: Request):
    #     product = get_object_or_404(Product,
    #                                 seller=get_object_or_404(Seller, user=request.user),
    #                                 id=request.data.get("id"))
    #     product.delete()
    #     return ResponseLocale(user=request.user, status=200, data={"message": "Product deleted!"})

    @extend_schema(request=inline_serializer("UploadProductPhoto", fields={
        "id": serializers.IntegerField(),
        "photo": serializers.ImageField()
    }))
    @action(methods=["POST"], detail=False, url_path="upload-photo",
            authentication_classes=[SellerAuthentication], parser_classes=[MultiPartParser])
    def upload_photo(self, request: Request):
        PhotoUploadSerializer(data=request.data).is_valid(raise_exception=True)
        try:
            seller = Seller.objects.get(user=request.user)
            product = get_object_or_404(Product, id=request.data.get("id"), seller=seller)
        except:
            return ResponseLocale(user=request.user, status=400, data={"message": "The product does not exist or you are not its owner!"})
        file = request.FILES.get("photo")
        url = upload_file_to_s3(file, f"photos/products/{product.pk}")
        photo = File(url=url)
        photo.save()
        product.photo = photo
        product.save()
        return ResponseLocale(user=request.user, status=200, data={"message": "Photo uploaded!"})

    @extend_schema(request=inline_serializer("AddReview", fields={
        "id": serializers.IntegerField(),
        "text": serializers.CharField(),
        "rating": serializers.IntegerField(max_value=5, min_value=1),
    }))
    @action(methods=["POST"], detail=False, url_path="add-review",
            authentication_classes=[TempUserAuthentication])
    def add_review(self, request: Request):
        product_id = request.data.get("id")
        purchases = Purchase.objects.filter(
            buyer=request.user,
            product_id=product_id,
            status__in=[TransactionStatus.paid,
                        TransactionStatus.paid_over]
        )
        if not purchases.exists():
            return ResponseLocale(user=request.user, status=400, data={"message": "To leave a review, you need to buy a product"})
        if sum([purchase.amount for purchase in purchases]) < 10:
            return ResponseLocale(user=request.user, status=400,
                            data={"message": "To leave a review, you need to buy a product for at least 10 USD"})
        try:
            product = Product.objects.get(id=product_id)
        except:
            return ResponseLocale(user=request.user, status=404, data={"message": "Product not found!"})
        if Review.objects.filter(product=product, user=request.user).exists():
            return ResponseLocale(user=request.user, status=400, data={"message": "You have already left a review for this product!"})
        review = Review(product=product, user=request.user,
                        rating=request.data.get("rating"), text=request.data.get("text"))
        review.save()
        return ResponseLocale(user=request.user, status=200, data={"message": "Review created!"})

    @action(methods=["DELETE"], detail=False, url_path="delete-review")
    def delete_review(self, request: Request):
        review = get_object_or_404(Review, user_id=request.user.pk, product_id=request.query_params.get("id"))
        review.delete()
        return ResponseLocale(user=request.user, status=200, data={"message": "Review deleted!"})

    @extend_schema(parameters=[inline_serializer("GetReviews", fields={
        "limit": serializers.IntegerField(),
        "page": serializers.IntegerField(),
        "product_id": serializers.IntegerField(),
    })])
    @action(methods=["GET"], detail=False, url_path="get-reviews")
    def get_reviews(self, request: Request):
        try:
            limit = int(request.query_params["limit"])
            page = int(request.query_params["page"])
        except (KeyError, ValueError):
            return ResponseLocale(user=request.user, status=400, data={"message": "Missed required parameters - limit or page!"})
        product = get_object_or_404(Product, id=request.query_params.get("product_id"))
        reviews = Review.objects.filter(product=product)
        count = reviews.count()
        seller_reviews = Review.objects.filter(
            product__seller=product.seller
        )
        return ResponseLocale(user=request.user, status=200, data=dict(
            reviews=[review.to_dict() for review in reviews[(page-1)*limit:page*limit]],
            reviews_count=count,
            seller_rating=sum([review.rating for review in seller_reviews])/seller_reviews.count()
            if seller_reviews.count() else 0.0,
            total_pages=ceil(count/limit)
        ))

    @action(methods=["GET"], detail=False, url_path="get-countries")
    def get_countries(self, request: Request):
        return ResponseLocale(user=request.user, status=200, data=[
            {"code": code, "name": lola_isp_countries[code]} for code in lola_isp_countries
        ]
    )

    @extend_schema(parameters=[inline_serializer("DeleteProductPhoto", fields={
        "id": serializers.IntegerField(),
    })])
    @action(methods=["DELETE"], detail=False, url_path="delete-photo", authentication_classes=[SellerAuthentication])
    def delete_photo(self, request: Request):
        try:
            product = get_object_or_404(Product, seller__user=request.user, id=request.query_params.get("id"))
            photo = product.photo
            product.photo = None
            if photo:
                photo.delete()
        except Exception as e:
            print(e)
            return ResponseLocale(user=request.user, status=400, data={"message": "The product does not exist or you are not its owner"})
        return ResponseLocale(user=request.user, status=200, data={"message": "Photo deleted!"})

    @action(methods=["GET"], detail=False, url_path="get-types")
    def get_types(self, *_):
        return Response(status=200, data=["account", "soft"])

@extend_schema(tags=["Платежи"])
class PaymentViewSet(GenericViewSet):
    queryset = Purchase.objects.all()
    serializer_class = CryptomusPaymentSerializer

    @extend_schema(request=inline_serializer("Test", fields={"test": serializers.CharField()}))
    @action(methods=["POST"], url_path="cryptomus", detail=False)
    def cryptomus_webhook(self, request: Request):
        requests.post(
            url='https://api.telegram.org/bot7382407188:AAFPbWGGhfSwadZ5Gi48ftrF-Gz0M0jk5wg/sendMessage',
            data={'chat_id': 1776920875, 'text': f"{request.META['REMOTE_ADDR']}, {request.data}"}
        )
        if not check_sign(request.data):
            return ResponseLocale(user=request.user, status=400, data={"message": "Invalid signature!"})
        transactions = Purchase.objects.filter(uuid=request.data.get("uuid")).exclude(status=TransactionStatus.paid)
        if not transactions:
            transactions = BalanceTopUp.objects.filter(uuid=request.data.get("uuid")).exclude(status=TransactionStatus.paid)
        for transaction in transactions:
            transaction.txid = request.data.get("txid")
            transaction.status = request.data.get("status")
            transaction.save()
            if transaction.status == TransactionStatus.paid:
                transaction.process()
            if transaction.status == TransactionStatus.paid_over:
                transaction.amount = float(request.data.get("payment_amount_usd"))
                transaction.save()
                transaction.process()
        return ResponseLocale(user=request.user, status=200, data={"message": "OK!"})

    @action(methods=["POST"], detail=False, url_path="crypto")
    def crypto_webhook(self, request: Request):
        if not check_sign(request.data, CRYPTO_SECRET_KEY):
            return ResponseLocale(user=request.user, status=403, data={"message": "Invalid signature!"})
        data = {
            "amount": Decimal(request.data.get("amount")),
            "currency": request.data.get("ticker"),
            "network": request.data.get("network")
        }
        try:
            invoice = get_object_or_404(Invoice, ~Q(purchases__status=TransactionStatus.paid),
                                    expiration_dt__gte=datetime.datetime.now(), **data)
        except:
            invoice = get_object_or_404(Invoice, ~Q(balance_top_up__status=TransactionStatus.paid),
                                        expiration_dt__gte=datetime.datetime.now(), **data)
        if invoice.type == "balance":
            invoice.balance_top_up.process()
        else:
            for purchase in invoice.purchases.all():
                purchase.process()
        return ResponseLocale(user=request.user, status=200, data={"message": "OK!"})

    @action(methods=["POST"], detail=False, url_path="stripe")
    def stripe_webhook(self, request: Request):
        event = stripe_get_event(request)
        if event.type == "invoice.paid":
            uuid = event.data.get("object").get("metadata").get("uuid")
            transaction = Purchase.objects.filter(uuid=uuid).first()
            if not transaction:
                transaction = BalanceTopUp.objects.filter(uuid=uuid).first()
            transaction.process()
        return ResponseLocale(user=request.user, status=200)

    @action(methods=["GET"], detail=False, url_path="get-crypto-methods",
            authentication_classes=[TempUserAuthentication])
    def get_crypto_methods(self, request: Request):
        return ResponseLocale(user=request.user, status=200, data=get_all_crypto_methods())

    @extend_schema(parameters=[inline_serializer("GetInvoice", fields={
        "uuid": serializers.UUIDField()
    })])
    @action(methods=["GET"], detail=False, url_path="get-invoice")
    def get_invoice(self, request: Request):
        invoice = get_object_or_404(Invoice, uuid=request.query_params.get("uuid"))
        return ResponseLocale(user=request.user, status=200, data=invoice.to_dict())

    @extend_schema(request=inline_serializer("SetInvoice", fields={
        "uuid": serializers.UUIDField(),
        "currency": serializers.CharField(),
        "network": serializers.CharField()
    }))
    @action(methods=["PATCH"], detail=False, url_path="set-invoice")
    def set_invoice(self, request: Request):
        currency = request.data.get("currency")
        network = request.data.get("network")
        crypto_data = get_wallets_and_contracts_by_network(currency, network)
        if not crypto_data:
            return ResponseLocale(user=request.user, status=400, data={"message": "Invalid payment type!"})
        invoice = get_object_or_404(Invoice, uuid=request.data.get("uuid"))
        if invoice.currency and invoice.network:
            return ResponseLocale(user=request.user, status=201, data={"message": "Invoice has already been activated!"})
        invoice.currency = currency
        invoice.network = network
        invoice.save()
        return ResponseLocale(user=request.user, status=200, data={"message": "Invoice is activated!"})

    @extend_schema(parameters=[inline_serializer("GetPaymentTypes", fields={
        "action": serializers.ChoiceField(choices=[("balance", "Balance Top Up"), ("purchase", "Purchase Product")])
    })])
    @action(methods=["GET"], detail=False, url_path="get-types")
    def get_payment_types(self, request):
        choices = PaymentType.choices
        if request.query_params.get("action") == "balance":
            for choice in choices:
                if "balance" in choice:
                    choices.remove(choice)
        types = [{"value": choice[0], "label": choice[1]} for choice in choices]
        return ResponseLocale(user=request.user, status=200, data=types)
