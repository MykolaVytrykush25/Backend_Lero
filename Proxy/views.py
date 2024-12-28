import datetime
import json

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework import serializers

from Main.models import Product, Purchase
from Main.utils import get_object_or_404
from Proxy.models import ProxyPurchase, ProxyProviders
from Proxy.providers import ProvidersFactory
from Users.utils import TempUserAuthentication


@extend_schema(tags=["Прокси"])
class ProxyViewSet(GenericViewSet):
    queryset = Product.objects.all()
    authentication_classes = [TempUserAuthentication]

    @extend_schema(parameters=[inline_serializer("GetProxyInfo", fields={
        "id": serializers.IntegerField()
    })])
    @action(methods=["GET"], detail=False, url_path="get-info")
    def get_info(self, request: Request):
        purchase_proxy = get_object_or_404(ProxyPurchase, purchase__buyer=request.user,
        purchase__id=request.query_params.get("id"))
        proxy_info = ProvidersFactory.get_provider(purchase_proxy.purchase.seller.user.username)(purchase_proxy)
        if purchase_proxy.expiration_date.timestamp() < datetime.datetime.now().timestamp():
            purchase_proxy.status = ProxyPurchase.ProxyPurchaseStatus.EXPIRED
            purchase_proxy.save()
            return Response(status=400, data={"message": "The tariff plan has expired! Please buy new one!"})
        else:
            proxy_info = proxy_info.generate_result()
            return Response(status=200, data=proxy_info)

    @extend_schema(request=inline_serializer("ChangeCredentialsProxy", fields={
        "id": serializers.IntegerField()
    }))
    @action(methods=["POST"], detail=False, url_path="change-credentials",
            authentication_classes=[TempUserAuthentication])
    def change_credentials(self, request: Request):
        purchase_proxy = get_object_or_404(ProxyPurchase, purchase__buyer=request.user,
                                           purchase__id=request.data.get("id"))
        if purchase_proxy.credentials_counter >= 5:
            return Response(status=400, data={"message": "Too many credential changes"})
        proxy_info = ProvidersFactory.get_provider(purchase_proxy.purchase.seller.user.username)(purchase_proxy)
        if not proxy_info.support_change_credentials:
            return Response(status=400, data={"message": "These proxies do not support changing credentials"})
        proxy_info.change_credentials()
        return Response(status=200, data={"message": "Credentials changed!"})


    @extend_schema(parameters=[inline_serializer("ProxyGetGeo", fields={
        "country_code": serializers.CharField(default="ru", required=False),
        "state": serializers.CharField(default="ryazanoblast", required=False),
        "provider": serializers.ChoiceField(choices=ProxyProviders.choices)
    })])
    @action(methods=["GET"], detail=False, url_path="get-geo")
    def get_geo(self, request: Request):
        country_code = request.query_params.get("country_code")
        state_code = request.query_params.get("state")
        cities_name = "cities"
        states_name = "states"
        countries_name = "countries"
        end_name = ".json"
        if request.query_params.get("provider") == ProxyProviders.PROXY_SELLER:
            end_name = "PrSel.json"
        if country_code and state_code:
            with open("static/"+cities_name+end_name, "r") as file:
                cities = json.load(file).get(country_code).get(state_code)
                if not cities:
                    return Response(status=200, data=[])
                data = [{"code": city.get("code"), "name": city.get("code")} for city in cities]
        elif country_code:
            with open("static/"+states_name+end_name, "r") as file:
                states = json.load(file).get(country_code)
                if not states:
                    return Response(status=200, data=[])
                if request.query_params.get("provider") == ProxyProviders.PROXY_SELLER:
                    data = [{"code": state.get("code"), "name": state.get("name")} for state in states]
                else:
                    data = [{"code": state, "name": state} for state in states]
        else:
            with open("static/"+countries_name+end_name, "r") as file:
                data = json.load(file)
        if request.query_params.get("provider") in [ProxyProviders.BOB, ProxyProviders.PROVIDER711]:
            cap_data = []
            for i in data:
                i["code"] = i["code"].upper()
                cap_data.append(i)
            return Response(status=200, data=cap_data)
        return Response(status=200, data=data)
