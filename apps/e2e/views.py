from django.conf import settings
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .seed import reset_and_seed


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def reset_view(request):
    """POST /api/__e2e__/reset/ — zera e semeia o mundo de E2E. Só sob E2E_MODE."""
    if not getattr(settings, 'E2E_MODE', False):
        return Response(status=404)
    return Response(reset_and_seed())
