from django.contrib import admin
from django.urls import path
from scheduler.views import schedule_dashboard, import_schedule_view, export_schedule_excel

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', schedule_dashboard, name='schedule_dashboard'),
    path('import/', import_schedule_view, name='import_schedule'),
    path('export/', export_schedule_excel, name='export_schedule'),
]
