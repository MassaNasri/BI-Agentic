from decimal import Decimal
from datetime import timedelta
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import User
from users.permissions import IsAdmin
from workspace.models import Workspace, WorkspaceMember

from .models import FreeTierUsage, Payment, Plan, Subscription
from .notification_client import get_notification_client
from .serializers import (
    AccessCheckSerializer,
    PaymentSerializer,
    PlanSerializer,
    SubscribeSerializer,
    SubscriptionSerializer,
)

logger = logging.getLogger(__name__)

LIMIT_REACHED_MESSAGE = 'You have reached your limit. Please subscribe.'


def _get_workspace_if_allowed(user, workspace_id):
    if user.role == 'admin':
        return Workspace.objects.filter(id=workspace_id).first()

    if user.role == 'manager':
        return Workspace.objects.filter(id=workspace_id, owner=user).first()

    membership = WorkspaceMember.objects.select_related('workspace').filter(
        workspace_id=workspace_id,
        user=user,
        status='active',
    ).first()
    return membership.workspace if membership else None


def _get_workspace_if_manager_or_admin(user, workspace_id):
    if user.role == 'admin':
        return Workspace.objects.filter(id=workspace_id).first()
    if user.role == 'manager':
        return Workspace.objects.filter(id=workspace_id, owner=user).first()
    return None


def _resolve_active_subscription(workspace_id):
    today = timezone.now().date()
    subscription = (
        Subscription.objects.select_related('plan')
        .filter(workspace_id=workspace_id, is_active=True)
        .order_by('-created_at')
        .first()
    )
    if not subscription:
        return None

    if subscription.end_date and subscription.end_date < today:
        subscription.is_active = False
        subscription.save(update_fields=['is_active', 'updated_at'])
        return None

    return subscription


def _check_and_optionally_consume(workspace_id, consume):
    free_limit = int(getattr(settings, 'FREE_TIER_VOICE_REQUEST_LIMIT', 3))
    today = timezone.now().date()

    with transaction.atomic():
        active_subscription = (
            Subscription.objects.select_for_update()
            .select_related('plan')
            .filter(workspace_id=workspace_id, is_active=True)
            .order_by('-created_at')
            .first()
        )

        if active_subscription and active_subscription.end_date and active_subscription.end_date < today:
            active_subscription.is_active = False
            active_subscription.save(update_fields=['is_active', 'updated_at'])
            active_subscription = None

        if active_subscription:
            limit = active_subscription.plan.max_voice_requests
            used = active_subscription.voice_requests_used
            allowed = used < limit

            if allowed and consume:
                active_subscription.voice_requests_used += 1
                active_subscription.save(update_fields=['voice_requests_used', 'updated_at'])
                used = active_subscription.voice_requests_used

            remaining = max(0, limit - used)
            return {
                'allowed': allowed,
                'remaining_requests': remaining,
                'limit': limit,
                'used_requests': used,
                'is_subscribed': True,
                'plan': {
                    'id': active_subscription.plan.id,
                    'name': active_subscription.plan.name,
                    'has_mcp_access': active_subscription.plan.has_mcp_access,
                },
            }

        usage, _ = FreeTierUsage.objects.select_for_update().get_or_create(
            workspace_id=workspace_id
        )
        used = usage.requests_used
        allowed = used < free_limit

        if allowed and consume:
            usage.requests_used += 1
            usage.save(update_fields=['requests_used', 'updated_at'])
            used = usage.requests_used

        remaining = max(0, free_limit - used)
        return {
            'allowed': allowed,
            'remaining_requests': remaining,
            'limit': free_limit,
            'used_requests': used,
            'is_subscribed': False,
            'plan': None,
        }


class HealthView(APIView):
    permission_classes = []

    def get(self, request):
        return Response(
            {
                'success': True,
                'service': 'subscription-service',
            },
            status=status.HTTP_200_OK,
        )


class PlanCatalogView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        plans = Plan.objects.filter(is_active=True).order_by('price_monthly', 'name')
        serializer = PlanSerializer(plans, many=True)
        return Response({'success': True, 'plans': serializer.data}, status=status.HTTP_200_OK)


class SubscribeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        workspace_id = serializer.validated_data['workspace_id']
        payment_method = serializer.validated_data['payment_method']
        plan = serializer.context['plan']

        if request.user.role not in ['manager', 'admin']:
            return Response(
                {'success': False, 'message': 'Only managers or admins can activate subscriptions.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        workspace = _get_workspace_if_manager_or_admin(request.user, workspace_id)
        if not workspace:
            return Response(
                {'success': False, 'message': 'Workspace not found or access denied.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        with transaction.atomic():
            today = timezone.now().date()
            Subscription.objects.filter(workspace_id=workspace_id, is_active=True).update(
                is_active=False,
                end_date=today,
                updated_at=timezone.now(),
            )

            subscription = Subscription.objects.create(
                workspace_id=workspace_id,
                plan=plan,
                start_date=today,
                end_date=today + timedelta(days=plan.duration_days),
                is_active=True,
                voice_requests_used=0,
                created_by_user_id=request.user.id,
            )

            payment = Payment.objects.create(
                user_id=request.user.id,
                workspace_id=workspace_id,
                subscription=subscription,
                amount=plan.price_monthly,
                payment_method=payment_method,
                status=Payment.STATUS_SUCCESS,
            )

        logger.info(
            'Subscription activated workspace=%s plan=%s user=%s payment=%s',
            workspace_id,
            plan.id,
            request.user.id,
            payment.id,
        )

        notification_client = get_notification_client()
        owner_email = workspace.owner.email if workspace and workspace.owner else None
        owner_name = workspace.owner.name if workspace and workspace.owner else None
        notification_result = notification_client.send_event(
            event_type='subscription_activated',
            event_key=f"subscription-activated:{subscription.id}",
            payload={
                'workspace_id': workspace_id,
                'workspace_name': workspace.name if workspace else None,
                'owner_email': owner_email,
                'owner_name': owner_name,
                'recipient_emails': [owner_email] if owner_email else [],
                'plan_name': plan.name,
                'duration_days': plan.duration_days,
                'start_date': subscription.start_date.isoformat() if subscription.start_date else None,
                'end_date': subscription.end_date.isoformat() if subscription.end_date else None,
                'subscription_id': subscription.id,
            },
        )
        if not notification_result.get('success'):
            logger.warning(
                'subscription_activated notification dispatch failed workspace=%s subscription=%s error=%s',
                workspace_id,
                subscription.id,
                notification_result.get('error'),
            )

        return Response(
            {
                'success': True,
                'message': 'Subscription activated successfully.',
                'subscription': SubscriptionSerializer(subscription).data,
                'payment': PaymentSerializer(payment).data,
            },
            status=status.HTTP_201_CREATED,
        )


class CheckAccessView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = AccessCheckSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        workspace_id = serializer.validated_data['workspace_id']
        consume = serializer.validated_data['consume']

        workspace = _get_workspace_if_allowed(request.user, workspace_id)
        if not workspace:
            return Response(
                {'success': False, 'message': 'Workspace not found or access denied.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        access_payload = _check_and_optionally_consume(workspace_id=workspace_id, consume=consume)
        response_payload = {
            'success': True,
            **access_payload,
        }

        if not access_payload['allowed']:
            response_payload['message'] = LIMIT_REACHED_MESSAGE

        return Response(response_payload, status=status.HTTP_200_OK)


class CurrentSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = AccessCheckSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        workspace_id = serializer.validated_data['workspace_id']

        workspace = _get_workspace_if_allowed(request.user, workspace_id)
        if not workspace:
            return Response(
                {'success': False, 'message': 'Workspace not found or access denied.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        subscription = _resolve_active_subscription(workspace_id=workspace_id)
        if not subscription:
            return Response(
                {'success': True, 'subscription': None},
                status=status.HTTP_200_OK,
            )

        return Response(
            {'success': True, 'subscription': SubscriptionSerializer(subscription).data},
            status=status.HTTP_200_OK,
        )


class AdminPlanListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        plans = Plan.objects.all().order_by('name')
        serializer = PlanSerializer(plans, many=True)
        return Response({'success': True, 'plans': serializer.data}, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = PlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = serializer.save()
        return Response(
            {'success': True, 'plan': PlanSerializer(plan).data},
            status=status.HTTP_201_CREATED,
        )


class AdminPlanDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def put(self, request, plan_id):
        plan = get_object_or_404(Plan, id=plan_id)
        serializer = PlanSerializer(instance=plan, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'success': True, 'plan': serializer.data}, status=status.HTTP_200_OK)

    def patch(self, request, plan_id):
        plan = get_object_or_404(Plan, id=plan_id)
        serializer = PlanSerializer(instance=plan, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'success': True, 'plan': serializer.data}, status=status.HTTP_200_OK)

    def delete(self, request, plan_id):
        plan = get_object_or_404(Plan, id=plan_id)
        if plan.subscriptions.exists():
            return Response(
                {
                    'success': False,
                    'message': 'Plan cannot be deleted because subscriptions already exist. Deactivate it instead.',
                },
                status=status.HTTP_409_CONFLICT,
            )
        plan.delete()
        return Response({'success': True, 'message': 'Plan deleted successfully.'}, status=status.HTTP_200_OK)


class AdminStatsView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        successful_payments = Payment.objects.filter(status=Payment.STATUS_SUCCESS)
        revenue = successful_payments.aggregate(
            total=Coalesce(Sum('amount'), Decimal('0.00'))
        )['total']
        free_tier_usage = FreeTierUsage.objects.aggregate(
            total=Coalesce(Sum('requests_used'), 0)
        )['total']
        subscribed_usage = Subscription.objects.aggregate(
            total=Coalesce(Sum('voice_requests_used'), 0)
        )['total']

        payload = {
            'success': True,
            'users': {
                'total': User.objects.count(),
                'active': User.objects.filter(is_active=True).count(),
                'admins': User.objects.filter(role='admin').count(),
            },
            'workspaces': {
                'total': Workspace.objects.count(),
            },
            'plans': {
                'total': Plan.objects.count(),
                'active': Plan.objects.filter(is_active=True).count(),
            },
            'subscriptions': {
                'total': Subscription.objects.count(),
                'active': Subscription.objects.filter(is_active=True).count(),
            },
            'payments': {
                'count': successful_payments.count(),
                'revenue': str(revenue),
            },
            'voice_usage': {
                'free_tier_requests': int(free_tier_usage or 0),
                'subscribed_requests': int(subscribed_usage or 0),
            },
        }
        return Response(payload, status=status.HTTP_200_OK)
