import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.db.models import Count, Q

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from .models import CustomUser, Machine, Manual, ManualChunk, QueryLog
from .serializers import MachineSerializer, ManualSerializer, QueryLogSerializer, AskQuestionSerializer
from .permissions import IsAdminRole, IsEngineerRole, IsSupervisorRole
from .rag_engine import ask_rag_pipeline, index_manual
from .tasks import index_manual_task
from .pdf_generator import generate_query_pdf_report
from products.models import Product
from inspections.models import Inspection


# ==========================================
# Template Views
# ==========================================

def index_redirect_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    if request.user.is_admin_role:
        return redirect('admin_dashboard')
    elif request.user.is_supervisor_role:
        return redirect('supervisor_dashboard')
    else:
        return redirect('engineer_dashboard')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('index_redirect')

    if request.method == 'POST':
        u = request.POST.get('username', '').strip()
        p = request.POST.get('password', '')
        user = authenticate(request, username=u, password=p)

        if user is not None:
            login(request, user)
            return redirect('index_redirect')
        else:
            messages.error(request, 'Invalid username or password. Please try again.')

    return render(request, 'login.html')


def register_view(request):
    """
    Public registration view:
    - Provides clean user onboarding
    - Strictly defaults to standard Engineer role
    - Prevents public privilege escalation to Supervisor or Administrator
    """
    if request.user.is_authenticated:
        return redirect('index_redirect')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not username or not password:
            messages.error(request, "Username and password are required.")
            return render(request, 'register.html')

        if len(password) < 6:
            messages.error(request, "Password must be at least 6 characters long.")
            return render(request, 'register.html')

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, 'register.html')

        if CustomUser.objects.filter(username=username).exists():
            messages.error(request, f"Username '{username}' is already taken.")
            return render(request, 'register.html')

        if email and CustomUser.objects.filter(email=email).exists():
            messages.error(request, f"An account with email '{email}' already exists.")
            return render(request, 'register.html')

        # Public users are strictly assigned the Engineer role
        user = CustomUser.objects.create_user(
            username=username,
            email=email,
            password=password,
            role=CustomUser.ROLE_ENGINEER
        )
        login(request, user)
        messages.success(request, f"Welcome to INOVEX, {user.username}! Your account has been registered.")
        return redirect('index_redirect')

    return render(request, 'register.html')


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def admin_dashboard_view(request):
    if not request.user.is_admin_role:
        return HttpResponseForbidden("Access Denied: Administrator role required.")

    machines = Machine.objects.all().prefetch_related('manuals', 'chunks')
    manuals = Manual.objects.all().select_related('machine', 'uploaded_by').prefetch_related('chunks')
    total_chunks = ManualChunk.objects.count()

    # Round 2: Products & Quality Inspections Management
    products = Product.objects.all().order_by('-created_at')
    products_count = products.count()
    active_products_count = products.filter(is_active=True).count()

    inspections = Inspection.objects.select_related('product', 'engineer', 'reviewed_by').order_by('-created_at')
    total_inspections = inspections.count()
    normal_count = inspections.filter(predicted_class='Normal').count()
    defective_count = inspections.filter(predicted_class='Defective').count()

    engineers = CustomUser.objects.filter(role=CustomUser.ROLE_ENGINEER)
    supervisors = CustomUser.objects.filter(role=CustomUser.ROLE_SUPERVISOR)

    context = {
        'machines': machines,
        'manuals': manuals,
        'total_chunks': total_chunks,
        'products': products,
        'products_count': products_count,
        'active_products_count': active_products_count,
        'inspections': inspections[:50],
        'total_inspections': total_inspections,
        'normal_count': normal_count,
        'defective_count': defective_count,
        'engineers': engineers,
        'supervisors': supervisors,
    }
    return render(request, 'admin_dashboard.html', context)


@login_required
def engineer_dashboard_view(request):
    # Supervisors should not use the engineer dashboard to ask questions
    if request.user.is_supervisor_role and not request.user.is_admin_role:
        return redirect('supervisor_dashboard')

    machines = Machine.objects.all()
    # Personal question history
    history = QueryLog.objects.filter(user=request.user).select_related('machine')[:20]

    # Round 2: Personal Inspection History
    inspections = Inspection.objects.filter(engineer=request.user).select_related('product').order_by('-created_at')
    total_count = inspections.count()
    normal_count = inspections.filter(predicted_class='Normal').count()
    defective_count = inspections.filter(predicted_class='Defective').count()

    context = {
        'machines': machines,
        'history': history,
        'recent_inspections': inspections[:5],
        'total_count': total_count,
        'normal_count': normal_count,
        'defective_count': defective_count,
    }
    return render(request, 'engineer_dashboard.html', context)


@login_required
def manufacturing_assistant_view(request):
    """
    Dedicated Manufacturing Assistant interface:
    - Equipment-isolated technical query consultation
    - Verifiable manual citations and PDF audit export
    """
    machines = Machine.objects.all().order_by('machine_id')
    history = QueryLog.objects.filter(user=request.user).select_related('machine').order_by('-timestamp')[:25]
    context = {
        'machines': machines,
        'history': history,
        'title': 'Manufacturing Assistant',
    }
    return render(request, 'manufacturing_assistant.html', context)


@login_required
def supervisor_dashboard_view(request):
    if not (request.user.is_supervisor_role or request.user.is_admin_role):
        return HttpResponseForbidden("Access Denied: Supervisor role required.")

    total_queries = QueryLog.objects.count()
    answered_count = QueryLog.objects.filter(status=QueryLog.STATUS_ANSWERED).count()
    unanswered_count = QueryLog.objects.filter(status=QueryLog.STATUS_INSUFFICIENT).count()
    
    recent_queries = QueryLog.objects.all().select_related('user', 'machine')[:30]
    unanswered_queries = QueryLog.objects.filter(status=QueryLog.STATUS_INSUFFICIENT).select_related('user', 'machine')[:20]

    context = {
        'total_queries': total_queries,
        'answered_count': answered_count,
        'unanswered_count': unanswered_count,
        'recent_queries': recent_queries,
        'unanswered_queries': unanswered_queries,
    }
    return render(request, 'supervisor_dashboard.html', context)


# ==========================================
# REST API Views
# ==========================================

class MachineListCreateAPIView(APIView):
    """
    GET: List all machines (Authenticated)
    POST: Register new machine (Admin only)
    """
    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAdminRole()]
        return [permissions.IsAuthenticated()]

    def get(self, request):
        machines = Machine.objects.all()
        serializer = MachineSerializer(machines, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = MachineSerializer(data=request.data)
        if serializer.is_valid():
            machine = serializer.save()
            return Response(MachineSerializer(machine).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ManualListCreateAPIView(APIView):
    """
    GET: List all manuals (Authenticated)
    POST: Upload PDF manual (Admin only) - Engineers/Supervisors get 403 Forbidden!
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAdminRole()]
        return [permissions.IsAuthenticated()]

    def get(self, request):
        manuals = Manual.objects.all().select_related('machine', 'uploaded_by')
        serializer = ManualSerializer(manuals, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = ManualSerializer(data=request.data)
        if serializer.is_valid():
            manual = serializer.save(uploaded_by=request.user)
            # Auto index synchronously or dispatch task
            try:
                index_manual(manual)
            except Exception as e:
                pass
            return Response(ManualSerializer(manual).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ManualIndexAPIView(APIView):
    """
    POST: Trigger re-indexing for a manual (Admin only)
    """
    permission_classes = [IsAdminRole]

    def post(self, request, pk):
        manual = get_object_or_404(Manual, pk=pk)
        count = index_manual(manual)
        return Response({
            'message': f'Successfully indexed {manual.document_id}',
            'chunks_created': count,
            'page_count': manual.page_count
        })


class AskQuestionAPIView(APIView):
    """
    POST: Ask maintenance question for a selected machine (Engineer or Admin).
    Supervisors have read-only access.
    """
    permission_classes = [IsEngineerRole]

    def post(self, request):
        serializer = AskQuestionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        machine_id = serializer.validated_data['machine_id'].strip()
        question = serializer.validated_data['question'].strip()

        try:
            machine = Machine.objects.get(machine_id=machine_id)
        except Machine.DoesNotExist:
            return Response({'error': f'Machine {machine_id} not found'}, status=status.HTTP_404_NOT_FOUND)

        # Execute RAG Pipeline
        rag_result = ask_rag_pipeline(machine_id=machine_id, question=question)

        # Persist Query and Answer in Database
        query_log = QueryLog.objects.create(
            user=request.user,
            machine=machine,
            question=question,
            answer=rag_result['answer'],
            status=rag_result['status'],
            citations=rag_result['citations']
        )

        return Response({
            'query_id': query_log.id,
            'machine_id': machine_id,
            'machine_name': machine.name,
            'question': question,
            'answer': rag_result['answer'],
            'status': rag_result['status'],
            'citations': rag_result['citations'],
            'timestamp': query_log.timestamp
        })


class QueryHistoryAPIView(APIView):
    """
    GET: Query history
    - Engineers get their own queries
    - Supervisors and Admins get all queries
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if request.user.is_engineer_role:
            queries = QueryLog.objects.filter(user=request.user).select_related('machine', 'user')
        else:
            queries = QueryLog.objects.all().select_related('machine', 'user')
        serializer = QueryLogSerializer(queries, many=True)
        return Response(serializer.data)


class UnansweredQueriesAPIView(APIView):
    """
    GET: Unanswered / Insufficient Evidence queries (Supervisor or Admin only)
    """
    permission_classes = [IsSupervisorRole]

    def get(self, request):
        queries = QueryLog.objects.filter(status=QueryLog.STATUS_INSUFFICIENT).select_related('machine', 'user')
        serializer = QueryLogSerializer(queries, many=True)
        return Response(serializer.data)


class DownloadQueryPdfAPIView(APIView):
    """
    Generate and stream an audit-ready, publication-grade A4 PDF maintenance report.
    Permissions:
    - Engineers can download reports for their own queries.
    - Supervisors and Administrators can download reports for any query.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, query_id):
        query_log = get_object_or_404(QueryLog, pk=query_id)

        # Permission check: Engineers can only download their own query reports
        if request.user.is_engineer_role and not (request.user.is_admin_role or request.user.is_supervisor_role):
            if query_log.user_id != request.user.id:
                return HttpResponseForbidden("Access Denied: You may only download maintenance reports for your own queries.")

        try:
            pdf_bytes = generate_query_pdf_report(query_log)
        except Exception as e:
            return Response({'error': f'Failed to generate PDF report: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        filename = f"Maintenance_Report_{query_log.machine.machine_id}_Q{query_log.id}.pdf"
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Content-Length'] = len(pdf_bytes)
        return response


download_query_pdf_view = DownloadQueryPdfAPIView.as_view()
