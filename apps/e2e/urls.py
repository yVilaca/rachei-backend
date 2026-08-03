from django.urls import path

from .views import reset_view

urlpatterns = [
    path('__e2e__/reset/', reset_view, name='e2e-reset'),
]
