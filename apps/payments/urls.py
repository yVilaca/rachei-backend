from django.urls import path

from .views import (
    AcertoConfirmarView,
    AcertoDetalheView,
    AcertoRejeitarView,
    AcertoView,
    AtividadeListView,
    ComprovanteArquivoView,
    ComprovanteCreateView,
    ConfirmarPagamentoView,
    DashboardView,
    LinkCobrancaCreateView,
    MarcarLidaView,
    PagamentoPublicoView,
    RejeitarPagamentoView,
)

app_name = 'payments'

urlpatterns = [
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('acertar/detalhe/', AcertoDetalheView.as_view(), name='acerto-detalhe'),
    path('acertar/<uuid:pk>/confirmar/', AcertoConfirmarView.as_view(), name='acerto-confirmar'),
    path('acertar/<uuid:pk>/rejeitar/', AcertoRejeitarView.as_view(), name='acerto-rejeitar'),
    path('acertar/', AcertoView.as_view(), name='acerto'),
    path('parcelas/<uuid:pk>/comprovante/', ComprovanteCreateView.as_view(), name='comprovante-create'),
    path('comprovantes/<uuid:pk>/arquivo/', ComprovanteArquivoView.as_view(), name='comprovante-arquivo'),
    path('parcelas/<uuid:pk>/confirmar/', ConfirmarPagamentoView.as_view(), name='confirmar-pagamento'),
    path('parcelas/<uuid:pk>/rejeitar/', RejeitarPagamentoView.as_view(), name='rejeitar-pagamento'),
    path('parcelas/<uuid:pk>/link-cobranca/', LinkCobrancaCreateView.as_view(), name='link-cobranca'),
    path('pagamento/<uuid:token>/', PagamentoPublicoView.as_view(), name='pagamento-publico'),
    # atividade/marcar-lida antes de atividade/ para resolução correta
    path('atividade/marcar-lida/', MarcarLidaView.as_view(), name='atividade-marcar-lida'),
    path('atividade/', AtividadeListView.as_view(), name='atividade-list'),
]
