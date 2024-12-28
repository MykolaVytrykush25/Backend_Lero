from rest_framework.routers import SimpleRouter

from Users.views import AdminViewSet, UserViewSet, SellerViewSet

users_router = SimpleRouter(trailing_slash=False)
users_router.register('api/v1/users', UserViewSet)

admin_router = SimpleRouter(trailing_slash=False)
admin_router.register('api/v1/admin', AdminViewSet)

seller_router = SimpleRouter(trailing_slash=False)
seller_router.register('api/v1/seller', SellerViewSet)
