from django.db import transaction
from rest_framework import serializers

from .models import Domain, Tenant


class DomainSerializer(serializers.ModelSerializer):
    class Meta:
        model = Domain
        fields = ["id", "domain", "is_primary"]


class TenantSerializer(serializers.ModelSerializer):
    """Lets a tenant-admin create/list tenants from the public host.

    Accepts a primary domain inline so the typical bootstrap (create company
    + give it a hostname) is one POST.
    """

    domain = serializers.CharField(write_only=True, required=True)
    domains = DomainSerializer(many=True, read_only=True)

    class Meta:
        model = Tenant
        fields = [
            "id",
            "schema_name",
            "name",
            "created_on",
            "is_active",
            "domain",
            "domains",
        ]
        read_only_fields = ["id", "created_on", "domains"]

    def validate_schema_name(self, value: str) -> str:
        if value == "public":
            raise serializers.ValidationError("Schema name 'public' is reserved.")
        if not value.replace("_", "").isalnum():
            raise serializers.ValidationError(
                "schema_name may only contain letters, digits and underscores."
            )
        return value.lower()

    def create(self, validated_data):
        domain = validated_data.pop("domain")
        with transaction.atomic():
            tenant = Tenant.objects.create(**validated_data)
            Domain.objects.create(domain=domain, tenant=tenant, is_primary=True)
        return tenant