from rest_framework import serializers

from .models import Payment, Plan, Subscription


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            'id',
            'name',
            'description',
            'badge',
            'price_monthly',
            'price_yearly',
            'duration_days',
            'max_voice_requests',
            'has_mcp_access',
            'features',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    plan_id = serializers.PrimaryKeyRelatedField(
        source='plan',
        queryset=Plan.objects.all(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = Subscription
        fields = [
            'id',
            'workspace_id',
            'plan',
            'plan_id',
            'start_date',
            'end_date',
            'is_active',
            'voice_requests_used',
            'created_by_user_id',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'voice_requests_used',
            'created_by_user_id',
            'created_at',
            'updated_at',
        ]


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            'id',
            'user_id',
            'workspace_id',
            'subscription',
            'amount',
            'payment_method',
            'status',
            'created_at',
        ]
        read_only_fields = ['id', 'status', 'created_at']


class SubscribeSerializer(serializers.Serializer):
    workspace_id = serializers.IntegerField(min_value=1)
    plan_id = serializers.IntegerField(min_value=1)
    payment_method = serializers.ChoiceField(
        choices=[Payment.PAYMENT_METHOD_VISA, Payment.PAYMENT_METHOD_BANK]
    )

    def validate_plan_id(self, value):
        try:
            plan = Plan.objects.get(id=value, is_active=True)
        except Plan.DoesNotExist:
            raise serializers.ValidationError('Selected plan does not exist or is inactive.')
        self.context['plan'] = plan
        return value


class AccessCheckSerializer(serializers.Serializer):
    workspace_id = serializers.IntegerField(min_value=1)
    consume = serializers.BooleanField(default=False)
