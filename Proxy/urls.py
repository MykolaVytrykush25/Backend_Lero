from rest_framework.routers import SimpleRouter

from Proxy.views import ProxyViewSet

proxy_router = SimpleRouter(trailing_slash=False)
proxy_router.register("api/v1/proxy", ProxyViewSet)
