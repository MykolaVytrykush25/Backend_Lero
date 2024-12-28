from rest_framework.routers import SimpleRouter

from Main.views import PaymentViewSet, ProductsViewSet

payment_router = SimpleRouter(trailing_slash=False)
payment_router.register("api/v1/payment", PaymentViewSet)

products_router = SimpleRouter(trailing_slash=False)
products_router.register("api/v1/products", ProductsViewSet)
