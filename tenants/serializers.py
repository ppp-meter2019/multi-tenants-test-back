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
        value = value.strip().lower()
        if value == "public":
            raise serializers.ValidationError("Schema name 'public' is reserved.")
        if not value.replace("_", "").isalnum():
            raise serializers.ValidationError(
                "schema_name may only contain letters, digits and underscores."
            )
        if Tenant.objects.filter(schema_name=value).exists():
            raise serializers.ValidationError(
                f"Tenant with schema '{value}' already exists."
            )
        return value

    def validate_domain(self, value: str) -> str:
        # Catch duplicate domains here so the caller gets a friendly 400 with
        # the offending value, not a 500 IntegrityError from the DB layer.
        value = value.strip().lower()
        if Domain.objects.filter(domain=value).exists():
            raise serializers.ValidationError(
                f"Domain '{value}' is already in use by another tenant."
            )
        return value

    def create(self, validated_data):
        domain = validated_data.pop("domain")
        with transaction.atomic():
            tenant = Tenant.objects.create(**validated_data)
            Domain.objects.create(domain=domain, tenant=tenant, is_primary=True)
        return tenant