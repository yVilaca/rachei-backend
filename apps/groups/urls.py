from django.urls import path

from .views import GrupoDetailView, GrupoListCreateView, MembroDestroyView, MembroListCreateView

app_name = 'groups'

urlpatterns = [
    path('grupos/', GrupoListCreateView.as_view(), name='grupo-list'),
    path('grupos/<uuid:pk>/', GrupoDetailView.as_view(), name='grupo-detail'),
    path('grupos/<uuid:grupo_pk>/membros/', MembroListCreateView.as_view(), name='membro-list'),
    path('grupos/<uuid:grupo_pk>/membros/<int:user_pk>/', MembroDestroyView.as_view(), name='membro-destroy'),
]
