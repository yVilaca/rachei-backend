from django.urls import path

from .views import (
    ConfirmarParticipacaoView,
    GrupoDetailView,
    GrupoListCreateView,
    GruposPendentesView,
    MembroDestroyView,
    MembroListCreateView,
)

app_name = 'groups'

urlpatterns = [
    path('grupos/', GrupoListCreateView.as_view(), name='grupo-list'),
    path('grupos/<uuid:pk>/', GrupoDetailView.as_view(), name='grupo-detail'),
    path('grupos/<uuid:grupo_pk>/membros/', MembroListCreateView.as_view(), name='membro-list'),
    path('grupos/<uuid:grupo_pk>/membros/<int:member_pk>/', MembroDestroyView.as_view(), name='membro-destroy'),
    path('grupos/<uuid:grupo_pk>/confirmar/', ConfirmarParticipacaoView.as_view(), name='grupo-confirmar'),
    path('me/grupos-pendentes/', GruposPendentesView.as_view(), name='grupos-pendentes'),
]
