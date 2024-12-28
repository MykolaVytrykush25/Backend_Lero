from logging.config import valid_ident

from django.contrib.auth.hashers import make_password, check_password
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework import serializers
from rest_framework.serializers import ModelSerializer

from Users.utils import send_code
from Users.models import User, Token, TgUser


class UserSerializer(ModelSerializer):
    password = serializers.CharField(min_length=8)
    email = serializers.EmailField()
    old_password = serializers.CharField(required=False)

    def create(self, validated_data):
        if User.objects.filter(email=validated_data.get('email')).exists():
            raise ValidationError({"message": 'The user with this email has already been registered!'})
        if User.objects.filter(email=validated_data.get('username')).exists():
            raise ValidationError({"message": 'The user with this username has already been registered!'})
        validated_data["password"] = make_password(validated_data["password"])
        user = User(**validated_data)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.get("password")
        old_password = validated_data.get("old_password")
        email = validated_data.get("email")
        if email:
            if User.objects.filter(email=email).exists():
                raise ValidationError({"message": "The user with this email has already exists"})
        if password:
            validated_data.pop("password")
        if instance.role == User.RoleChoices.temp_user:
            if password:
                validated_data["password"] = make_password(password)
                instance.role = User.RoleChoices.user
                instance.save()
                if instance.password:
                    tokens = Token.objects.filter(user=instance)
                    tokens.delete()
            return super().update(instance, validated_data)
        if old_password:
            if not check_password(old_password, instance.password):
                raise PermissionDenied({"message": "Incorrect password!"})
            if password:
                validated_data["password"] = make_password(password)
                tokens = Token.objects.filter(user=instance)
                tokens.delete()
        return super().update(instance, validated_data)

    class Meta:
        model = User
        fields = ["email", "password", "username", "old_password", "description", "referral_from", "locale"]
