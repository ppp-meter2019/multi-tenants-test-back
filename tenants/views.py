from rest_framework import viewsets

from .models import Tenant
from .permissions import IsTenantAdminOnPublic
from .serializers import TenantSerializer


class TenantViewSet(viewsets.ModelViewSet):
    """CRUD over tenants. Reachable only on the public host."""

    queryset = Tenant.objects.exclude(schema_name="public").order_by("-created_on")
    serializer_class = TenantSerializer
    permission_classes = [IsTenantAdminOnPublic]