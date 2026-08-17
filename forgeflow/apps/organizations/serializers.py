from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.organizations.models import APIKey, Membership, MembershipRole, Organization, Team

User = get_user_model()


class OrganizationSerializer(serializers.ModelSerializer):
    current_user_role = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ['id', 'name', 'slug', 'current_user_role', 'member_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_current_user_role(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        membership = obj.memberships.filter(user=request.user).first()
        return membership.role if membership else None

    @extend_schema_field(serializers.IntegerField())
    def get_member_count(self, obj):
        return obj.memberships.count()


class OrganizationCreateSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(required=False)

    class Meta:
        model = Organization
        fields = ['id', 'name', 'slug', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_slug(self, value):
        if value and Organization.objects.filter(slug=value).exists():
            raise serializers.ValidationError("An organization with this slug already exists.")
        return value

    def create(self, validated_data):
        user = self.context['request'].user
        if not validated_data.get('slug'):
            base_slug = slugify(validated_data['name'])
            slug = base_slug
            counter = 1
            while Organization.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            validated_data['slug'] = slug

        with transaction.atomic():
            organization = Organization.objects.create(**validated_data)
            # Creator automatically becomes OWNER
            Membership.objects.create(
                user=user,
                organization=organization,
                role=MembershipRole.OWNER,
            )
        return organization


class MembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ['id', 'user', 'role', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class MembershipCreateSerializer(serializers.Serializer):
    email = serializers.EmailField(write_only=True, required=True)
    role = serializers.ChoiceField(choices=MembershipRole.choices, default=MembershipRole.DEVELOPER)

    def validate(self, attrs):
        email = attrs['email']
        organization = self.context['organization']

        user = User.objects.filter(email=email).first()
        if not user:
            raise serializers.ValidationError({'email': 'User with this email does not exist.'})

        if Membership.objects.filter(user=user, organization=organization).exists():
            raise serializers.ValidationError({'email': 'User is already a member of this organization.'})

        attrs['user'] = user
        return attrs

    def create(self, validated_data):
        organization = self.context['organization']
        return Membership.objects.create(
            user=validated_data['user'],
            organization=organization,
            role=validated_data['role'],
        )

    def to_representation(self, instance):
        return MembershipSerializer(instance, context=self.context).data


class MembershipUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Membership
        fields = ['role']

    def validate_role(self, value):
        instance = self.instance
        if instance.role == MembershipRole.OWNER and value != MembershipRole.OWNER:
            # Prevent demoting the only owner
            owner_count = Membership.objects.filter(
                organization=instance.organization,
                role=MembershipRole.OWNER,
            ).count()
            if owner_count <= 1:
                raise serializers.ValidationError("Cannot demote the only OWNER of the organization.")
        return value
