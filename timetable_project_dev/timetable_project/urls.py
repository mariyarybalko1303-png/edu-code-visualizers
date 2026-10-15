from django.contrib import admin
from django.urls import path
from scheduler import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.schedule_dashboard, name='schedule'),
    path('time-table/student/', views.public_student_timetable_view, name='public_student_timetable'),
    path('time-table/teacher/', views.public_teacher_timetable_view, name='public_teacher_timetable'),
    path('api/student-filters/', views.student_filters_api, name='student_filters_api'),
    path('api/teacher-filters/', views.teacher_filters_api, name='teacher_filters_api'),
    path('students/', views.students_view, name='students_list'),
    path('students/<int:student_id>/schedule/', views.student_schedule_view, name='student_schedule'),
    path('teachers/', views.teachers_view, name='teachers_list'),
    path('export/', views.export_schedule_excel, name='export_schedule'),
    path('import/', views.import_schedule_view, name='import_schedule'),
]
