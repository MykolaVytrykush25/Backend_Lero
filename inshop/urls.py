from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from Main.urls import payment_router, products_router
from Proxy.urls import proxy_router
from Users.urls import users_router, admin_router, seller_router

urlpatterns = [
    path('', include(users_router.urls)),
    path("", include(seller_router.urls)),
    path('', include(admin_router.urls)),
    path('', include(payment_router.urls)),
    path('', include(proxy_router.urls)),
    path('', include(products_router.urls)),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path("api/v1/docs/", SpectacularSwaggerView.as_view(url_name='schema'), name='docs'),

]
