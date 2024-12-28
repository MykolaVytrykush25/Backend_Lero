import math
import time
from datetime import timedelta, datetime

from uuid import uuid4

import requests
import json

from copy import deepcopy

from dateutil import parser
from faker import Faker
from requests.auth import HTTPBasicAuth
from rest_framework.response import Response

from django.conf import settings

from Main.celery import app
from Main.models import Category, Purchase, Product, PaymentType, TransactionStatus

from Proxy.models import ProxyProviders, ProxyTypes, ProxyPurchase, get_expiration_date
from inshop.settings import logger, GEONODE_API_URL


@app.task(name='buy_proxy', bind=True)
def buy_proxy(*args, **kwargs):
    proxy_purchase = ProxyPurchase.objects.get(purchase_id=kwargs.get("proxy_purchase"))
    ProvidersFactory.get_provider(proxy_purchase.purchase.seller.user.username)(proxy_purchase).start()
    return True

with open('static/static_proxy.json', 'r') as file:
    static_data = json.load(file)

lola_isp_countries = {
    "virm": "United Kingdom",
    "dtag": "Germany",
    "juic": "United States",
    "vocu": "Australia",
    "dtag_nl": "Netherlands",
    "pol": "Poland",
    "bra": "Brazil",
    "lva": "Latvia",
    "fra": "France",
    "rou": "Romania",
    "can": "Canada",
    "nor": "Norway",
    "aut": "Austria",
    "ukr": "Ukraine",
    "tur": "Turkey",
    "jpn": "Japan",
    "isr": "Israel",
    "twn": "Taiwan",
    "kor": "South Korea",
    "esp": "Spain",
    "sgp": "Singapore",
    "hkn": "Hong Kong",
    "tha": "Thailand",
    "ind": "India",
    "ita": "Italy"
}



class Proxies:
    def __init__(self, proxy_purchase):
        self.proxy_purchase = proxy_purchase
        self.count = proxy_purchase.count
        self.proxy_type = proxy_purchase.type.name
        self.country = proxy_purchase.country
        self.user_account = proxy_purchase.purchase.buyer
        self.provider = proxy_purchase.purchase.seller.user.username
        self.support_change_credentials = None

    def start(self):
        # try:
        if not self.proxy_purchase.extend_of or self.proxy_type == ProxyTypes.ISP:
            self.create_plan()
        else:
            self.prolong_plan()
        # except:
        #     self.proxy_purchase.purchase.status = TransactionStatus.cancel
        #     self.proxy_purchase.purchase.buyer.balance += float(self.proxy_purchase.purchase.amount)
        #     self.proxy_purchase.purchase.save()
        #     self.proxy_purchase.purchase.buyer.save()
        self.proxy_purchase.status = ProxyPurchase.ProxyPurchaseStatus.ACTIVE
        self.proxy_purchase.save()
        return self.get_plan_info()

    @staticmethod
    def handle_response(response):
        if response.status_code != 200:
            logger.error(f"Error response: {response.status_code} - {response.text}")
            return None
        logger.info(f"Successful response: {response.status_code}")
        return json.loads(response.text)

    @staticmethod
    def _isp_static_generate(static, proxies, proxy_type=None):
        statics = []
        for proxy in proxies:
            current_static = deepcopy(static)
            if proxy_type == ProxyTypes.DATA_CENTER:
                current_static['country'] = proxy.country
            ip, port, username, password = proxy.split(":")
            current_static["login"] = username
            current_static["password"] = password
            for protocol in static["protocols"]:
                for sub_protocol in static["protocols"][protocol]:
                    current_static["protocols"][protocol][sub_protocol]["host"] = ip
                    current_static["protocols"][protocol][sub_protocol]["port"] = [port, port]
            statics.append(current_static)
        return statics

    @staticmethod
    def generate_static():
        return deepcopy(static_data)

    def _generate_result(self, static_name, user="", password="", proxies=None, proxy_type=None):
        static = self.generate_static().copy().get(static_name)
        if user and password:
            static['login'] = user
            static['password'] = password
            return static
        else:
            return Proxies._isp_static_generate(static, proxies, proxy_type)

    def get_plan_info(self):
        pass

    def read_plan(self):
        pass

    def get_traffic_left(self):
        pass

    def prolong_plan(self):
        pass

    def create_plan(self):
        pass

    def generate_result(self):
        pass

    def change_credentials(self):
        pass


class LightningProxies(Proxies):
    def create_plan_request(self, data):
        url = f'{settings.LOLA_HOST}/api/getplan/{self.proxy_type}'
        logger.info(f"Creating plan request with data: {data}")
        print(data)
        response = requests.post(url, headers=settings.LOLA_HEADERS, data=data)
        print(response.text)
        return self.handle_response(response).get('PlanID')

    def plan_info(self):
        """
        Получение времени создание
        До какого действует
        """
        plan_id = self.proxy_purchase.service_data.get('plan')
        url = f"{settings.LOLA_HOST}/api/info/{plan_id}"
        logger.info(f"Fetching plan info for plan_id: {plan_id}")
        response = requests.get(url, headers=settings.LOLA_HEADERS)
        print("info lola ", response.text)
        return self.handle_response(response)

    def read_plan(self):
        """
        Получение результата прокси
        """
        plan_id = self.proxy_purchase.service_data.get('plan')
        url = f"{settings.LOLA_HOST}/api/plan/{self.proxy_type}/read/{plan_id}"
        logger.info(f"read plan info for plan_id: {plan_id}")
        response = requests.get(url, headers=settings.LOLA_HEADERS)
        print("read lola ", response.text)
        return self.handle_response(response)

    def get_traffic_left(self):
        return self.read_plan().get("bandwidthLeft")

    def get_and_read_plan(self):
        data = {}
        plan_info = self.plan_info()
        read_plan = self.read_plan()
        try:
            data.update(plan_info)
            data.update(read_plan)
        except Exception as e:
            print(e)
            return None
        return data

    def get_plan_info(self):
        plan_info = self.get_and_read_plan()
        if not plan_info:
            return None
        duration = plan_info.get("duration", None)
        bandwidth = plan_info.get("bandwidth", None)
        bandwidth_left = plan_info.get("bandwidthLeft", None)
        expiration_date = plan_info.get('expiration_date', None)
        created_date = plan_info.get('created_date', None)

        result = {
            "duration": duration,
            "bandwidth": bandwidth if bandwidth else None,
            "bandwidth_left": bandwidth_left if bandwidth_left else None,
            "expiration_date": expiration_date,
            "created_date": created_date
        }
        filtered_result = {key: value for key, value in result.items() if value is not None}
        return filtered_result

    def prolong_plan(self):
        plan_id = self.proxy_purchase.extend_of.service_data.get("plan")
        url = f"{settings.LOLA_HOST}/api/add/{plan_id}/{self.count}"
        logger.info(f"Adding residential proxies to plan_id: {plan_id} with count: {self.count}")
        response = requests.post(url, headers=settings.LOLA_HEADERS)
        self.handle_response(response)
        self.proxy_purchase.extend_of.count += self.count
        self.proxy_purchase.extend_of.expiration_date = get_expiration_date()
        self.proxy_purchase.extend_of.save()

    def create_plan(self):
        data_variants = {
            ProxyTypes.RESIDENTIAL: {"bandwidth": self.count},
            ProxyTypes.ISP: {'ip': self.count, "region": self.country},
            ProxyTypes.DATA_CENTER: {"plan": str(self.count)}
        }
        data = data_variants.get(self.proxy_type)
        logger.info(f"Creating new plan with data: {data}")
        plan_id = self.create_plan_request(data)
        self.proxy_purchase.service_data["plan"] = plan_id
        self.proxy_purchase.save()
        success = 5
        while success != 0:
            try:
                plan_info = self.read_plan()
                print(plan_info)
                if self.proxy_type == ProxyTypes.RESIDENTIAL:
                    self.proxy_purchase.service_data = dict(plan=plan_id,
                                                            username=plan_info.get("user"),
                                                            password=plan_info.get("pass"))
                else:
                    self.proxy_purchase.service_data = dict(plan=plan_id,
                                                            proxies=plan_info.get("proxies"))
                success = 0
            except:
                time.sleep(1)
                success -= 1
        self.proxy_purchase.save()

    @staticmethod
    def handle_request(data):
        country_code = data.get('country_code')
        state = data.get('state')
        if not country_code and not state:
            response = requests.post(f"{settings.LOLA_HOST}/api/getlist/country_list",
                                     headers=settings.LOLA_HEADERS)
        elif country_code and not state:
            response = requests.post(
                f"{settings.LOLA_HOST}/api/getlist/state_list", headers=settings.LOLA_HEADERS,
                data={"country_code": (None, country_code)}
            )
        elif country_code and state:
            response = requests.post(
                f"{settings.LOLA_HOST}/api/getlist/city_list", headers=settings.LOLA_HEADERS,
                data={"country_code": (None, country_code), "state": (None, state)},
            )
        else:
            return Response(status=400, data={"message": "Invalid input"})

        return Response(status=200, data=json.loads(response.text))

    def generate_result(self):
        print(self.proxy_purchase.service_data)
        if self.proxy_type == ProxyTypes.RESIDENTIAL:
            print(1)
            return super()._generate_result("lola",
                                            self.proxy_purchase.service_data.get("username"),
                                            self.proxy_purchase.service_data.get("password"))
        return super()._generate_result("lola",
                                        proxies=self.proxy_purchase.service_data.get("proxies"),
                                        proxy_type=self.proxy_type)


class Provider711(Proxies):
    def __init__(self, proxy_purchase):
        self.headers = {
            "Authorization": f"Bearer {settings.PROVIDER711_API_TOKEN}"
        }
        super().__init__(proxy_purchase)

    def create_plan(self):
        expiration_dt = str(int((datetime.now() + timedelta(days=30)).timestamp()))
        data = {
            "expire": expiration_dt,
            "flow": str(self.count*1000000000),
        }
        response = requests.post(
            f"{settings.PROVIDER711_API_URL}/eapi/order/",
            json=data,
            headers=self.headers
        )
        logger.error(response.status_code, response.text)
        data = response.json()
        if data.get("error"):
            logger.info(f"Provider711 Error response when create plan - status {response.status_code}: {response.text}")
        self.proxy_purchase.service_data = {
            "plan_id": data["order_no"],
            "username": data["username"],
            "password": data["passwd"],
            "rest_id": data["restitution_no"]
        }
        self.proxy_purchase.save()

    def prolong_plan(self):
        proxy_data = self.proxy_purchase.extend_of.service_data
        expiration_dt = str(int((datetime.now() + timedelta(days=30)).timestamp()))
        data = {
            "expire": expiration_dt,
            "username": proxy_data.get("username"),
            "flow": str(int(self.count*1000000000))
        }
        response = requests.post(f'{settings.PROVIDER711_API_URL}/eapi/order/allocate',
                                 json=data, headers=self.headers)
        logger.error(response.status_code, response.text)
        data = response.json()
        if data.get("error"):
            logger.error(f"Provider711 Error when prolong plan - status {response.status_code}: {response.text}")
        self.proxy_purchase.extend_of.count += self.count
        self.proxy_purchase.extend_of.expiration_date = get_expiration_date()
        self.proxy_purchase.extend_of.save()

    def get_traffic_left(self):
        plan_id = self.proxy_purchase.service_data.get("plan_id")
        if self.proxy_purchase.extend_of:
            plan_id = self.proxy_purchase.extend_of.service_data.get("plan_id")
        response = requests.get(f"{settings.PROVIDER711_API_URL}/eapi/order/", params={
            "order_no": plan_id,
        }, headers=self.headers)
        data = response.json()
        if data.get("error"):
            logger.error(f"Provider711 Error when receiving traffic - status {response.status_code}: {response.text}")
        return int(data.get("un_flow")) / 1000000000

    def generate_result(self):
        return super()._generate_result("seva",
                                        user=self.proxy_purchase.service_data.get("username"),
                                        password=self.proxy_purchase.service_data.get("password"),
                                        proxy_type=self.proxy_type)


class BobProxies(Proxies):
    GEO_NODE_HEADER = {"r-api-key": settings.GEONODE_API_KEY}

    def plan_info(self):
        """
        Получение времени создание
        До какого действует
        """
        plan = self.proxy_purchase.service_data
        url = f"{GEONODE_API_URL}/api/reseller/user/{plan.get('id')}"
        logger.info(f"Fetching plan info for plan_id: {plan.get('id')}")
        response = self.handle_response(requests.get(url, headers=self.GEO_NODE_HEADER,
                                                     auth=HTTPBasicAuth(plan.get('username'), plan.get('password'))))
        print("info bob ", response)
        return response

    def get_traffic_left(self):
        usage_bandwidth = self.read_plan().get("data").get("usageBandwidth")*math.pow(10, -6)
        count_now = self.proxy_purchase.count
        if self.proxy_purchase.extend_of:
            count_now = self.proxy_purchase.extend_of.count
        return (count_now*1000-usage_bandwidth)/1000

    def read_plan(self):
        """
        Получение результата прокси
        """
        if not self.proxy_purchase.extend_of:
            plan = self.proxy_purchase.service_data
        else:
            plan = self.proxy_purchase.extend_of.service_data
        url = f"{GEONODE_API_URL}/api/reseller/user/traffic/{plan.get('id')}"
        logger.info(f"read plan info for plan_id: {plan.get('id')}")
        response = self.handle_response(requests.get(url, headers=self.GEO_NODE_HEADER,
                                                     auth=HTTPBasicAuth(plan.get('username'), plan.get('password'))))
        print("read bob ", response)
        return response

    def get_and_read_plan(self):
        data = {}
        try:
            plan_info = self.plan_info().get("data")
            read_plan = self.read_plan().get("data")
            data.update(plan_info)
            data.update(read_plan)
        except:
            return None
        return data

    def get_plan_info(self):
        plan_info = self.get_and_read_plan()
        if not plan_info:
            return None
        duration = plan_info.get('traffic_limit')
        bandwidth = plan_info.get('traffic_limit')
        bandwidth_left = int(bandwidth) - int(plan_info.get('usageBandwidth'))
        expiration_date = plan_info.get('current_period_end')
        created_date = plan_info.get('current_period_start')

        result = {
            "duration": duration,
            "bandwidth": bandwidth/1000 if bandwidth else None,
            "bandwidth_left": bandwidth_left/1000,
            "expiration_date": expiration_date,
            "created_date": created_date
        }
        print(result)
        filtered_result = {key: value for key, value in result.items() if value is not None}
        return filtered_result

    def create_plan(self):
        url = f'{GEONODE_API_URL}/api/reseller/user/create'
        fake = Faker()
        random_username = fake.user_name()
        random_email = fake.email()
        password = str(uuid4())
        data = {
            "email": random_email,
            "serviceType": "RESIDENTIAL-PREMIUM" if self.proxy_type == ProxyTypes.RESIDENTIAL else "SHARED-DATACENTER",
            "traffic_limit": self.count * 1000,
            "username": random_username,
            "password": password,
        }
        logger.info(f"Creating plan request with data: {data}")
        response = requests.post(url, headers=self.GEO_NODE_HEADER, json=data)
        data = self.handle_response(response)
        self.proxy_purchase.service_data=dict(
                username=random_username,
                password=password,
                email=random_email,
                id=data['data']['id'])
        self.proxy_purchase.save()

    def prolong_plan(self):
        proxy_info = self.proxy_purchase.extend_of
        plan_info = BobProxies(proxy_info).get_plan_info()
        url_add = f"{GEONODE_API_URL}/api/reseller/user/{proxy_info.service_data['id']}"
        new_expiration_dt = parser.isoparse(plan_info['expiration_date']) + timedelta(days=30)
        data = {
            "subscription_status": "active",
            "traffic_limit": self.get_traffic_left() * 1000 + self.count * 1000,
            "password": proxy_info.service_data['password'],
            "current_period_end": new_expiration_dt.strftime(
                '%Y-%m-%dT%H:%M:%S') + 'Z',
        }
        logger.info(f"geo service exists {data} sending this")
        result_add = requests.put(url_add, headers=self.GEO_NODE_HEADER, json=data)
        self.proxy_purchase.extend_of.count += self.count
        self.proxy_purchase.extend_of.save()
        logger.info(f"response from geo {result_add.json()}")

    def generate_result(self):
        plan_info = self.proxy_purchase.service_data
        return super()._generate_result("bob", plan_info.get("username"),
                                        plan_info.get("password"))


class ProxyResellerProvider(Proxies):
    def __init__(self, proxy_purchase):
        super().__init__(proxy_purchase)
        self.support_change_credentials = True
    
    def get_plan_info(self):
        if not self.proxy_purchase.service_data.get("login") and not self.proxy_purchase.extend_of:
            plan_id = self.proxy_purchase.service_data.get("plan")
            response = requests.put(
                f"{settings.RESELLER_PROXY_BASE_URL}/residentsubuser/list/tools?package_key={plan_id}"
            ).json()
            user_data = response["data"]
            try:
                self.proxy_purchase.service_data["username"] = user_data["login"]
                self.proxy_purchase.service_data["password"] = user_data["password"]
                self.proxy_purchase.save()
            except KeyError:
                logger.error(f"Invalid response received: {response}")
                return None
        return self.proxy_purchase.service_data

    def prolong_plan(self):
        try:
            traffic = self.count*1000000000
            response = requests.get(f"{settings.RESELLER_PROXY_BASE_URL}/residentsubuser/packages")
            response.raise_for_status()

            all_packages = response.json()
            if all_packages.get("status") != "success":
                logger.error(f"Failed to fetch packages: {all_packages}")
                return
            plan_id = self.proxy_purchase.extend_of.service_data.get("plan")
            for tariff in all_packages.get("data", []):
                logger.info(tariff)
                if tariff.get("package_key") == plan_id:
                    traffic += int(tariff["traffic_limit"])
                    expired_at = datetime.now() + timedelta(days=30)
                    logger.info(traffic)
                    data = {
                        "expired_at": f"{expired_at.day}.{expired_at.month}.{expired_at.year}",
                        "is_active": True,
                        "traffic_limit": traffic,
                        "package_key": plan_id,
                    }

                    update_response = requests.post(
                        f"{settings.RESELLER_PROXY_BASE_URL}/residentsubuser/update", json=data
                    )
                    update_response.raise_for_status()
                    update_result = update_response.json()
                    logger.info(update_result)
                    if update_result.get("status") == "success":
                        result_data = update_result.get("data", {})
                        self.proxy_purchase.extend_of.expiration_date = result_data.get("expired_at", {}).get(
                            "date"
                        )
                        self.proxy_purchase.extend_of.count += self.count
                        self.proxy_purchase.extend_of.save()
                    else:
                        error_message = update_result.get("errors", [{"message": "Unknown error"}])[0].get("message")
                        logger.error(f"Failed to update service user: {update_result}")
                        raise ValueError(f"Update failed: {error_message}")
        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise ValueError("Failed to communicate with the reseller service")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise ValueError("An unexpected error occurred while updating the service user")

    def change_credentials(self):
        self.count = self.get_traffic_left()
        response = requests.delete(
            f"{settings.RESELLER_PROXY_BASE_URL}/residentsubuser/delete?",
            params={"package_key": self.proxy_purchase.service_data.get('plan')}
        )
        response.raise_for_status()
        self.create_plan()
        self.proxy_purchase.credentials_counter += 1
        self.proxy_purchase.save()

    def create_plan(self):
        try:
            expired_at = datetime.now() + timedelta(weeks=4)
            traffic = self.count*1000000000

            data = {
                "rotation": -1,
                "traffic_limit": traffic,
                "expired_at": f"{expired_at.day}.{expired_at.month}.{expired_at.year}",
                "is_link_date": False,
            }

            response = requests.post(f"{settings.RESELLER_PROXY_BASE_URL}/residentsubuser/create", data=data)
            response.raise_for_status()

            request_result = response.json()

            if request_result.get("status") == "success":
                result_data = request_result.get("data", {})
                package_key = result_data.get("package_key")
                self.proxy_purchase.service_data = dict(plan=package_key)
                self.proxy_purchase.expiration_date = result_data.get("expired_at", {}).get("date")
                logger.info(f"ServiceUser created successfully with package key: {package_key}")
            else:
                logger.error(f"Failed to create new user: {request_result}")
            self.get_plan_info()
        except requests.RequestException as e:
            logger.error(f"Request to create new user failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error occurred while creating new user: {e}")

    def generate_result(self):
        plan_info = self.proxy_purchase.service_data
        if not self.proxy_purchase.service_data.get("username"):
            self.get_plan_info()
        return super()._generate_result("proxy-seller", plan_info.get("username"),
                                        plan_info.get("password"))

    def get_traffic_left(self):
        response = requests.get(f"{settings.RESELLER_PROXY_BASE_URL}/residentsubuser/packages")
        response.raise_for_status()
        result = response.json()
        data = result.get("data", {})
        if not data:
            return 0
        for item in data:
            if item["package_key"] == self.proxy_purchase.service_data.get("plan"):
                logger.info(f"{item['package_key']} - {item['traffic_left']}")
                traffic_left = item["traffic_left"] / 1000000000
                return traffic_left

class ProxyPropProvider(Proxies):
    def _get_category_id(self, category_name):
        response = requests.post(
            f"{settings.DROP_PROXY_BASE_URL}/categories",
            headers=settings.DROP_PROXY_HEADER,
            params=settings.DROP_PROXY_PARAMS_GET,
        )
        response.raise_for_status()
        categories = json.loads(response.text)

        for key, value in categories.items():
            if value.get("name") == category_name:
                return value.get("id")
        logger.warning(f"Category '{category_name}' not found.")
        return None

    def _get_product_id(self, category_id, product_name):
        response = requests.post(
            f"{settings.DROP_PROXY_BASE_URL}/goods",
            headers=settings.DROP_PROXY_HEADER,
            params=settings.DROP_PROXY_PARAMS_GET,
        )
        response.raise_for_status()
        goods = response.json().get("goods", {})

        for item in goods.values():
            if item.get("id_cat") == category_id and item.get("name").replace(" ", "") == product_name:
                return item.get("id")
        logger.warning(f"Product '{product_name}' not found in category ID {category_id}.")
        return None

    def _create_order(self, product_id):
        data = settings.DROP_PROXY_PARAMS_ORDER.copy()
        data["type"] = int(product_id)
        data["count"] = 1
        data["rules"] = 1
        response = requests.post(
            f"{settings.DROP_PROXY_BASE_URL}/createorder", headers=settings.DROP_PROXY_HEADER, data=data
        )
        response.raise_for_status()
        logger.info(response.text)
        order_result = response.json()
        if order_result.get("ok") == "TRUE":
            return order_result.get("invoice")
        logger.warning("Failed to create order.")
        raise ValueError("Failed to create order")

    def _pay_order(self, invoice):
        data = settings.DROP_PROXY_DATA_PAY
        response = requests.post(
            f"{settings.DROP_PROXY_BASE_URL}/paybalance/{invoice}",
            headers=settings.DROP_PROXY_HEADER,
            data=data,
        )
        response.raise_for_status()
        logger.info(response.text)
        return response.json().get("invoice")

    def _download_credentials(self, invoice):
        response = requests.post(
            f"{settings.DROP_PROXY_BASE_URL}/downloadtxt/{invoice}", headers=settings.DROP_PROXY_HEADER
        )
        response.raise_for_status()
        file_content = response.text
        logger.info(file_content)
        lines = file_content.split(";")
        login, password, coupon = None, None, None

        for line in lines:
            if "LOGIN" in line:
                login = line.split(":")[1].strip()
            elif "PASSWORD" in line:
                password = line.split(":")[1].strip()
            elif "Your coupon" in line:
                coupon = line.split(":")[1].strip()

        if (login and password) or coupon:
            return login, password, coupon
        logger.warning("Failed to extract LOGIN and PASSWORD or COUPON from file content.")
        return None, None, None

    def create_plan(self):
        try:
            category_name = "Резидентские Прокси IPV4"
            start_package = self._get_start_package()
            product_name = self._get_product_name(start_package)

            category_id = self._get_category_id(category_name)
            if not category_id:
                return
            product_id = self._get_product_id(category_id, product_name)
            if not product_id:
                return

            invoice = self._create_order(product_id)
            if not invoice:
                raise ValueError("Failed to create order")

            paid_invoice = self._pay_order(invoice)
            login, password, coupon = self._download_credentials(paid_invoice)
            if login and password:
                self.proxy_purchase.service_data = dict(
                    plan=paid_invoice, coupon=coupon, password=password, login=login
                )
                self.proxy_purchase.save()
                logger.info("ServiceUser created successfully.")
            else:
                logger.warning("Failed to create ServiceUser due to missing credentials.")
            packages = self._get_packages()
            if packages:
                self.proxy_purchase.extend_of = self.proxy_purchase
                self.proxy_purchase.save()
                self.prolong_plan()
                self.proxy_purchase.extend_of = None
                self.proxy_purchase.save()
        except requests.RequestException as e:
            logger.error(f"Request to create new user failed: {e}")
        except ValueError as e:
            logger.error(f"In except: {e}")
            raise ValueError(e)
        except Exception as e:
            logger.error(f"Unexpected error occurred while creating new user: {e}")

    def prolong_plan(self):
        try:
            category_name = "Продление прокси"
            packages = self._get_packages()
            for package in packages:
                product_name = self._get_renewal_product_name(package)

                category_id = self._get_category_id(category_name)
                if not category_id:
                    return

                product_id = self._get_product_id(category_id, product_name)
                if not product_id:
                    return
                invoice = self._create_order(product_id)
                if not invoice:
                    raise ValueError("Failed to create order")

                paid_invoice = self._pay_order(invoice)
                if not paid_invoice:
                    return

                login, password, coupon = self._download_credentials(paid_invoice)
                if coupon:
                    logger.info(f"Refill package with coupon {self.get_coupon(package)}")
                    response = requests.get(
                        f"{settings.DROP_PROXY_BUY_URL}/sub-account/"
                        f"{self.proxy_purchase.extend_of.service_data.get('login')}"
                        f"/refill/{coupon}/v6r890YmOUuzLX8Lw5v6c98enZROmwFomEfDenuckfV87ITgcyT5PCVnLkT8"
                    )
                    logger.info(response.text)
                    response.raise_for_status()
                    logger.info("ServiceUser updated successfully.")
                else:
                    logger.warning("Failed to update ServiceUser due to missing credentials.")
        except requests.RequestException as e:
            logger.error(f"Request to create new user failed: {e}")
        except ValueError as e:
            logger.error(f"In except: {e}")
            raise ValueError(e)
        except Exception as e:
            logger.error(f"Unexpected error occurred while creating new user: {e}")
        self.proxy_purchase.extend_of.count += self.count
        self.proxy_purchase.extend_of.expiration_date = get_expiration_date()
        self.proxy_purchase.extend_of.save()

    def get_traffic_left(self):
        data = self.proxy_purchase.service_data
        url = (f"{settings.DROP_PROXY_BUY_URL}/sub-account/{data.get('login')}/"
               f"v6r890YmOUuzLX8Lw5v6c98enZROmwFomEfDenuckfV87ITgcyT5PCVnLkT8")
        response = requests.get(url)
        response.raise_for_status()
        text_response = response.text
        result = json.loads(text_response)
        bandWidth = result.get("bandWidth")
        bandWidthLimit = result.get("bandWidthLimit")
        if not bandWidthLimit:
            return 0
        return float(bandWidthLimit) - float(bandWidth)

    def _get_product_name(self, traffic):
        raise NotImplementedError("Subclasses should implement this method to return the product name")

    def _get_renewal_product_name(self, traffic):
        raise NotImplementedError("Subclasses should implement this method to return the renewal product name")

    def _get_start_package(self):
        package_sizes = [10, 5, 1]
        for size in package_sizes:
            if self.count >= size:
                self.count -= size
                return size

    def _get_packages(self):
        packages = []
        remaining_count = self.count
        package_sizes = [1000, 100, 50, 10, 5, 1]

        for size in package_sizes:
            while remaining_count >= size:
                packages.append(size)
                remaining_count -= size

        return packages

    def get_coupon(self, count=None):
        if not count:
            count = self.count
        coupons = {
            1: "2CdFB4cF136A040626C2E58ee121CeE7C7E0d5bDa36d773497b934dBD287582B",
            5: "21924bC13d9dCE86d34605e8460285A075293a3E1d016407cCA3ACA357816654",
            10: "21924bC13d9dCE86d34605e8460285A075293a3E1d016407cCA3ACA357816654",
            50: "21924bC13d9dCE86d34605e8460285A075293a3E1d016407cCA3ACA357816654",
            100: "18A89080E4a589782A8bD70d991331633487B14d0012B629aB5b77bfdd828bF5",
            1000: "b4EC68a9f3A78122609e2Dc1B29e5922cDA269F673303e41FbC4c77D6e4cEFf8"
        }
        return coupons.get(count)


class ProxyDropProvider1(ProxyPropProvider):
    service_type = "proxy-drop1"

    def generate_result(self):
        return super()._generate_result("drop-1",
                                        f"user-{self.proxy_purchase.service_data.get('login')}",
                                        self.proxy_purchase.service_data.get("password"))

    def _get_product_name(self, traffic):
        return f"ПУЛ№1РезидентныеПроксиIPV4-{traffic}GBТрафика(ПУЛ100М)[SOCKS5/HTTP]"

    def _get_renewal_product_name(self, traffic):
        return f"ПУЛ№1Купоннапродлениепрокси+{traffic}ГБтрафика"


class ProxyDropProvider2(ProxyPropProvider):
    service_type = "proxy-drop2"

    def generate_result(self):
        return super()._generate_result("drop-2",
                                        self.proxy_purchase.service_data.get("login"),
                                        self.proxy_purchase.service_data.get("password"))

    def _get_product_name(self, traffic):
        return f"ПУЛ№2РезидентныеПроксиIPV4-100MBТрафика(ПУЛ120М)[SOCKS5/HTTP]"

    def _get_renewal_product_name(self, traffic):
        return f"ПУЛ№2Купоннапродлениепрокси+{traffic}ГБтрафика"

class ProvidersFactory:
    providers_map = {
        ProxyProviders.LIGHTNING: LightningProxies,
        ProxyProviders.BOB: BobProxies,
        ProxyProviders.PROXY_SELLER: ProxyResellerProvider,
        ProxyProviders.PROXY_DROP_PULL_1: ProxyDropProvider1,
        ProxyProviders.PROXY_DROP_PULL_2: ProxyDropProvider2,
        ProxyProviders.PROVIDER711: Provider711
    }

    @classmethod
    def get_provider(cls, provider):
        return cls.providers_map.get(provider)


@app.task
def gift_proxy_plan(user_id):
    product = Product.objects.get(seller__user__username=ProxyProviders.PROXY_SELLER,
                                  categories__in=[Category.objects.get(name=ProxyTypes.RESIDENTIAL)])
    purchase = Purchase(
        amount=0,
        quantity=1,
        payment_type=PaymentType.bonus,
        buyer_id=user_id,
        product=product,
        seller=product.seller,
        status=TransactionStatus.paid,
        expired_at=get_expiration_date()
    )
    purchase.save()
    proxy_purchase = ProxyPurchase(
        purchase=purchase,
        type=Category.objects.get(name=ProxyTypes.RESIDENTIAL),
        count=1
    )
    proxy_purchase.save()
    provider_purchase = ProxyResellerProvider(proxy_purchase)
    provider_purchase.count = 0.1
    provider_purchase.create_plan()
    return True

