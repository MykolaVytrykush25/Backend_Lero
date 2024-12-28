import os
import time

from celery import Celery, shared_task

from inshop import settings
import requests

from inshop.settings import logger, PROXY_SELLER_API_CODE, PROXY_SELLER_API_COUPON

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "inshop.settings")
app = Celery("Main", broker=settings.CELERY_BROKER_URL)
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
# @shared_task(name="prolong_main_proxy_plan")
# def prolong_main_proxy_plan(*_):
#     response = requests.post(f"https://proxy-seller.com/personal/api/v1/{PROXY_SELLER_API_CODE}/order/make", json={
#         "paymentId": 1,
#         "tarifId": 25208,
#         "coupon": PROXY_SELLER_API_COUPON,
#     })
#     logger.info(f"Successful prolong ProxySeller main-plan, response {response.status_code}: {response.text}")
#     print(f"Successful prolong ProxySeller main-plan, response {response.status_code}: {response.text}")
#     if response.json().get("status") != "success":
#         logger.error(f"Error with prolong ProxySeller main plan, response {response.status_code}: {response.text}")
#         return False
#     return True
@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')