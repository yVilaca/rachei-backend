from django.urls import path

from .views import DespesaCreateView, DespesaDetailView, DespesasPorGrupoView, ParcelaDetailView

app_name = 'debts'

urlpatterns = [
    path('grupos/<uuid:grupo_pk>/despesas/', DespesasPorGrupoView.as_view(), name='despesa-list'),
    path('despesas/', DespesaCreateView.as_view(), name='despesa-create'),
    path('despesas/<uuid:pk>/', DespesaDetailView.as_view(), name='despesa-detail'),
    path('parcelas/<uuid:pk>/', ParcelaDetailView.as_view(), name='parcela-detail'),
]
