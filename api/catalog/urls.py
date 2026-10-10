from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("produkter/<str:product_id>/", views.product, name="product"),
    path("health/", views.health, name="health"),
    path("api/v1/", views.api_index, name="api_index"),
    path("api/v1/latest/", views.api_latest, name="api_latest"),
    path("api/v1/runs/", views.api_runs, name="api_runs"),
    path("api/v1/products/", views.api_products, name="api_products"),
    path("api/v1/products/<str:product_id>/", views.api_contract, name="api_contract"),
    path("api/v1/products/<str:product_id>/data/", views.api_data, name="api_data"),
]
