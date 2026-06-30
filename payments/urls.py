from django.urls import path

from .views import (
    AtividadeListView,
    ComprovanteCreateView,
    ConfirmarPagamentoView,
    LinkCobrancaCreateView,
    MarcarLidaView,
    PagamentoPublicoView,
)

app_name = 'payments'

urlpatterns = [
    path('parcelas/<uuid:pk>/comprovante/', ComprovanteCreateView.as_view(), name='comprovante-create'),
    path('parcelas/<uuid:pk>/confirmar/', ConfirmarPagamentoView.as_view(), name='confirmar-pagamento'),
    path('parcelas/<uuid:pk>/link-cobranca/', LinkCobrancaCreateView.as_view(), name='link-cobranca'),
    path('pagamento/<uuid:token>/', PagamentoPublicoView.as_view(), name='pagamento-publico'),
    # atividade/marcar-lida antes de atividade/ para resolução correta
    path('atividade/marcar-lida/', MarcarLidaView.as_view(), name='atividade-marcar-lida'),
    path('atividade/', AtividadeListView.as_view(), name='atividade-list'),
]
