from rest_framework import serializers
from rest_framework.exceptions import ValidationError, PermissionDenied

from Main.models import PaymentType, Product, Category, Tag, TransactionStatus
from Main.utils import get_object_or_404


class PurchaseSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    quantity = serializers.IntegerField(required=False)
    products = serializers.ListField(child=serializers.JSONField(required=True), required=False)
    payment_type = serializers.ChoiceField(choices=PaymentType.choices, required=True)

    def is_valid(self, *, raise_exception=False):
        data = self.initial_data
        if data.get("products"):
            try:
                for product in data.get("products"):
                    if not product.get("id") or not product.get("quantity"):
                        raise ValidationError({"message": "Invalid products data!"})
                    if product.get("quantity") <= 0:
                        raise ValidationError({"message": "Invalid quantity!"})
            except:
                raise ValidationError({"message": "Invalid products data!"})
        else:
            if not data.get("id"):
                raise ValidationError({"message": "Missed required parameter id!"})
            if not data.get("quantity"):
                raise ValidationError({"message": "Missed required parameter quantity!"})
            if data.get("quantity") <= 0:
                raise ValidationError({"message": "Invalid quantity!"})
        return super().is_valid(raise_exception=raise_exception)


class GetCardsSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=Product.ProductTypes.choices, required=False)
    category = serializers.CharField(required=False)
    tags = serializers.CharField(default="1,2,3", required=False)


class ProductSerializer(serializers.ModelSerializer):
    category = serializers.IntegerField(required=True)
    tags = serializers.ListField(child=serializers.IntegerField(required=True), required=False)

    def create(self, validated_data):
        category = get_object_or_404(Category, id=validated_data.get("category"))
        if validated_data.get("type") == Product.ProductTypes.proxy:
            raise PermissionDenied({"message": "The action is prohibited!"})
        tags = validated_data.get("tags")
        if tags:
            tags = Tag.objects.filter(id__in=tags)
            validated_data.pop("tags")
        validated_data.pop("category")
        prices = {}
        try:
            for price in validated_data.get("prices"):
                prices[price["amount"]] = float(price["price"])
        except:
            raise ValidationError({"message": "Invalid price-list!"})
        validated_data["prices"] = prices
        validated_data["in_stock"] = 0
        product = Product.objects.create(**validated_data)
        product.categories.add(category)
        if tags:
            product.tags.add(*tags)
        product.save()
        return product

    class Meta:
        model = Product
        fields = ["title", "short_description", "description",
                  "prices", "in_stock", "type", "seller", "category", "tags"]

class PhotoUploadSerializer(serializers.Serializer):
    photo = serializers.ImageField()


class CryptomusPaymentSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(required=True)
    status = serializers.ChoiceField(choices=TransactionStatus.choices, required=True)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["name", "description", "type"]
