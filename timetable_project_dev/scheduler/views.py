import csv
import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.db.models import Q
from .models import Teacher, Student, Subject, Room, TeacherUnavailability, LessonRequirement, ScheduleItem
from .solver import TimetableCSPSolver

DAYS_ORDER = [
    ("Monday", "Понеділок"),
    ("Tuesday", "Вівторок"),
    ("Wednesday", "Середа"),
    ("Thursday", "Четвер"),
    ("Friday", "П'ятниця")
]

def schedule_dashboard(request):
    current_week = int(request.GET.get('week', 1))
    edit_unavail_id = request.GET.get('edit_unavail')
    editing_unavail = None
    if edit_unavail_id:
        editing_unavail = TeacherUnavailability.objects.filter(id=edit_unavail_id).first()

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add_teacher":
            name = request.POST.get("name", "").strip()
            if name:
                Teacher.objects.create(name=name)
                messages.success(request, f"Викладача «{name}» додано!")
            return redirect(f"/?week={current_week}")

        elif action == "add_subject":
            title = request.POST.get("title", "").strip()
            if title:
                Subject.objects.create(title=title)
                messages.success(request, f"Дисципліну «{title}» додано!")
            return redirect(f"/?week={current_week}")

        elif action == "add_room":
            number = request.POST.get("number", "").strip()
            if number:
                Room.objects.get_or_create(number=number)
                messages.success(request, f"Аудиторію {number} додано!")
            return redirect(f"/?week={current_week}")

        elif action == "manual_assign":
            day = request.POST.get("day")
            period = int(request.POST.get("period"))
            teacher_id = request.POST.get("teacher_id")
            subject_id = request.POST.get("subject_id")
            room_id = request.POST.get("room_id")
            groups = request.POST.get("groups", "").strip()
            is_stream = bool(request.POST.get("is_stream"))

            if day == "Monday" and period > 7:
                messages.error(request, "У понеділок не може бути 8-ї пари!")
                return redirect(f"/?week={current_week}")

            teacher = Teacher.objects.get(id=teacher_id)
            subject = Subject.objects.get(id=subject_id)
            room = Room.objects.get(id=room_id) if room_id else None

            if ScheduleItem.objects.filter(week=current_week, day=day, period=period, teacher=teacher).exists():
                messages.error(request, f"Колізія: {teacher.name} вже має пару в цей час!")
                return redirect(f"/?week={current_week}")

            if room and ScheduleItem.objects.filter(week=current_week, day=day, period=period, room=room).exists():
                messages.error(request, f"Колізія: аудиторія {room.number} уже зайнята на цій парі!")
                return redirect(f"/?week={current_week}")

            ScheduleItem.objects.update_or_create(
                week=current_week,
                day=day,
                period=period,
                defaults={
                    'teacher': teacher,
                    'subject': subject,
                    'room': room,
                    'groups': groups,
                    'is_stream': is_stream
                }
            )
            messages.success(request, f"Пару «{subject.title}» призначено в розклад!")
            return redirect(f"/?week={current_week}")

        elif action == "delete_lesson":
            item_id = request.POST.get("item_id")
            if item_id:
                item = ScheduleItem.objects.filter(id=item_id, week=current_week).first()
                if item:
                    subj_title = item.subject.title
                    item.delete()
                    messages.success(request, f"Пару «{subj_title}» видалено з розкладу!")
            return redirect(f"/?week={current_week}")

        elif action == "save_unavailability":
            unavail_id = request.POST.get("unavail_id")
            teacher_id = request.POST.get("teacher_id")
            day = request.POST.get("day")
            period = int(request.POST.get("period", 0))

            if unavail_id:
                un = TeacherUnavailability.objects.filter(id=unavail_id).first()
                if un:
                    un.teacher_id = teacher_id
                    un.day = day
                    un.period = period
                    un.save()
                    messages.success(request, f"Зайнятість викладача {un.teacher.name} оновлено!")
            else:
                TeacherUnavailability.objects.create(teacher_id=teacher_id, day=day, period=period)
                messages.success(request, "Зайнятість викладача зафіксовано!")
            return redirect(f"/?week={current_week}")

        elif action == "delete_unavailability":
            unavail_id = request.POST.get("unavail_id")
            if unavail_id:
                un = TeacherUnavailability.objects.filter(id=unavail_id).first()
                if un:
                    t_name = un.teacher.name
                    un.delete()
                    messages.success(request, f"Обмеження для {t_name} видалено!")
            return redirect(f"/?week={current_week}")

        elif action == "add_requirement":
            teacher_id = request.POST.get("teacher_id")
            subject_id = request.POST.get("subject_id")
            groups = request.POST.get("groups", "").strip()
            is_stream = bool(request.POST.get("is_stream"))
            hours = int(request.POST.get("hours", 1))

            LessonRequirement.objects.create(
                week=current_week,
                teacher_id=teacher_id,
                subject_id=subject_id,
                groups=groups,
                is_stream=is_stream,
                hours_per_week=hours
            )
            messages.success(request, "Вимогу до навантаження додано!")
            return redirect(f"/?week={current_week}")

        elif action == "auto_generate":
            rooms = list(Room.objects.all())
            if not rooms:
                messages.error(request, "Додайте хоча б одну аудиторію!")
                return redirect(f"/?week={current_week}")

            requirements = list(LessonRequirement.objects.filter(week=current_week))
            if not requirements:
                messages.error(request, "Немає вимог навантаження для цього тижня!")
                return redirect(f"/?week={current_week}")

            unavailabilities = list(TeacherUnavailability.objects.all())

            solver = TimetableCSPSolver(
                week=current_week,
                teachers=Teacher.objects.all(),
                subjects=Subject.objects.all(),
                rooms=rooms,
                requirements=requirements,
                unavailabilities=unavailabilities
            )

            solution = solver.solve()
            if solution is None:
                messages.error(request, "Неможливо розставити пари без колізій з поточними обмеженнями!")
            else:
                ScheduleItem.objects.filter(week=current_week).delete()
                for item in solution:
                    ScheduleItem.objects.create(**item)
                messages.success(request, f"Розклад успішно згенеровано ({len(solution)} пар)!")

            return redirect(f"/?week={current_week}")

    items = ScheduleItem.objects.filter(week=current_week).select_related('teacher', 'subject', 'room')
    grid = {p: {} for p in range(1, 9)}
    for it in items:
        grid[it.period][it.day] = it

    context = {
        'current_week': current_week,
        'editing_unavail': editing_unavail,
        'teachers': Teacher.objects.all(),
        'subjects': Subject.objects.all(),
        'rooms': Room.objects.all(),
        'unavailabilities': TeacherUnavailability.objects.select_related('teacher').all(),
        'requirements': LessonRequirement.objects.filter(week=current_week).select_related('teacher', 'subject'),
        'days_order': DAYS_ORDER,
        'periods': range(1, 9),
        'grid': grid
    }
    return render(request, "schedule.html", context)

# ----------------- СТОРОНА КОРИСТУВАЧА: time-table/student -----------------
def public_student_timetable_view(request):
    faculties = Student.objects.values_list('faculty', flat=True).distinct().order_by('faculty')
    
    selected_faculty = request.GET.get('faculty', '').strip()
    selected_course = request.GET.get('course', '').strip()
    selected_group = request.GET.get('group', '').strip()
    selected_student_id = request.GET.get('student_id', '').strip()
    current_week = int(request.GET.get('week', 1))

    selected_student = None
    if selected_student_id:
        selected_student = Student.objects.filter(id=selected_student_id).first()

    group_to_show = ""
    if selected_student:
        group_to_show = selected_student.group_name
    elif selected_group:
        group_to_show = selected_group

    lessons = []
    if group_to_show:
        items = ScheduleItem.objects.filter(week=current_week).select_related('teacher', 'subject', 'room')
        day_order = {"Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4, "Friday": 5}
        for it in items:
            groups_list = [g.strip().lower() for g in it.groups.split(',')]
            if group_to_show.strip().lower() in groups_list or not it.groups:
                lessons.append(it)
        lessons.sort(key=lambda x: (day_order.get(x.day, 9), x.period))

    return render(request, "student_public_timetable.html", {
        'faculties': faculties,
        'selected_faculty': selected_faculty,
        'selected_course': selected_course,
        'selected_group': selected_group,
        'selected_student': selected_student,
        'selected_student_id': selected_student_id,
        'group_to_show': group_to_show,
        'lessons': lessons,
        'current_week': current_week,
    })

def student_filters_api(request):
    faculty = request.GET.get('faculty', '').strip()
    course = request.GET.get('course', '').strip()
    group = request.GET.get('group', '').strip()

    qs = Student.objects.all()
    if faculty:
        qs = qs.filter(faculty=faculty)

    courses = list(qs.values_list('course', flat=True).distinct().order_by('course'))

    if course:
        qs = qs.filter(course=int(course))

    groups = list(qs.values_list('group_name', flat=True).distinct().order_by('group_name'))

    students = []
    if group:
        qs = qs.filter(group_name=group)
        students = list(qs.values('id', 'full_name').order_by('full_name'))

    return JsonResponse({
        'courses': courses,
        'groups': groups,
        'students': students
    })

# ----------------- СТОРОНА КОРИСТУВАЧА: time-table/teacher -----------------
def public_teacher_timetable_view(request):
    departments = Teacher.objects.exclude(department="").values_list('department', flat=True).distinct().order_by('department')
    
    selected_dept = request.GET.get('department', '').strip()
    selected_teacher_id = request.GET.get('teacher_id', '').strip()
    current_week = int(request.GET.get('week', 1))

    selected_teacher = None
    if selected_teacher_id:
        selected_teacher = Teacher.objects.filter(id=selected_teacher_id).first()

    lessons = []
    if selected_teacher:
        items = ScheduleItem.objects.filter(week=current_week, teacher=selected_teacher).select_related('teacher', 'subject', 'room')
        day_order = {"Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4, "Friday": 5}
        lessons = sorted(items, key=lambda x: (day_order.get(x.day, 9), x.period))

    return render(request, "teacher_public_timetable.html", {
        'departments': departments,
        'selected_dept': selected_dept,
        'selected_teacher': selected_teacher,
        'selected_teacher_id': selected_teacher_id,
        'lessons': lessons,
        'current_week': current_week,
    })

def teacher_filters_api(request):
    dept = request.GET.get('department', '').strip()
    qs = Teacher.objects.all()
    if dept:
        qs = qs.filter(department=dept)
    teachers = list(qs.values('id', 'name').order_by('name'))
    return JsonResponse({'teachers': teachers})

# ----------------- БАЗА СТУДЕНТІВ -----------------
def students_view(request):
    edit_id = request.GET.get('edit')
    editing_student = None
    if edit_id:
        editing_student = Student.objects.filter(id=edit_id).first()

    q_search = request.GET.get('search', '').strip()
    f_faculty = request.GET.get('faculty', '').strip()
    f_course = request.GET.get('course', '').strip()
    f_group = request.GET.get('group', '').strip()

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save":
            student_id = request.POST.get("student_id")
            full_name = request.POST.get("full_name", "").strip()
            faculty = request.POST.get("faculty", "").strip()
            course = int(request.POST.get("course", 1))
            group_name = request.POST.get("group_name", "").strip()

            if student_id:
                s = get_object_or_404(Student, id=student_id)
                s.full_name = full_name
                s.faculty = faculty
                s.course = course
                s.group_name = group_name
                s.save()
                messages.success(request, f"Дані студента «{full_name}» оновлено!")
            else:
                Student.objects.create(
                    full_name=full_name,
                    faculty=faculty,
                    course=course,
                    group_name=group_name
                )
                messages.success(request, f"Студента «{full_name}» додано до бази!")
            return redirect("students_list")

        elif action == "delete":
            student_id = request.POST.get("student_id")
            s = Student.objects.filter(id=student_id).first()
            if s:
                s.delete()
                messages.success(request, "Студента видалено з бази!")
            return redirect("students_list")

    students_qs = Student.objects.all()

    if q_search:
        students_qs = students_qs.filter(full_name__icontains=q_search)
    if f_faculty:
        students_qs = students_qs.filter(faculty=f_faculty)
    if f_course:
        students_qs = students_qs.filter(course=int(f_course))
    if f_group:
        students_qs = students_qs.filter(group_name=f_group)

    students = students_qs.order_by("course", "group_name", "full_name")

    faculties = Student.objects.values_list('faculty', flat=True).distinct().order_by('faculty')
    groups = Student.objects.values_list('group_name', flat=True).distinct().order_by('group_name')

    return render(request, "students.html", {
        'students': students,
        'editing_student': editing_student,
        'faculties': faculties,
        'groups': groups,
        'q_search': q_search,
        'f_faculty': f_faculty,
        'f_course': f_course,
        'f_group': f_group,
    })

def student_schedule_view(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    current_week = int(request.GET.get('week', 1))

    all_items = ScheduleItem.objects.filter(week=current_week).select_related('teacher', 'subject', 'room')
    
    student_lessons = []
    for item in all_items:
        assigned_groups = [g.strip().lower() for g in item.groups.split(',')]
        if student.group_name.strip().lower() in assigned_groups or not item.groups:
            student_lessons.append(item)

    day_map_order = {"Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4, "Friday": 5}

    student_lessons.sort(key=lambda x: (day_map_order.get(x.day, 9), x.period))

    disciplines_summary = {}
    for l in student_lessons:
        subj = l.subject.title
        if subj not in disciplines_summary:
            disciplines_summary[subj] = {
                'title': subj,
                'teacher': l.teacher.name,
                'room': l.room.number if l.room else "—",
                'is_stream': l.is_stream,
                'count': 0
            }
        disciplines_summary[subj]['count'] += 1

    return render(request, "student_schedule.html", {
        'student': student,
        'current_week': current_week,
        'lessons': student_lessons,
        'disciplines_summary': disciplines_summary.values()
    })

# ----------------- БАЗА ВИКЛАДАЧІВ -----------------
def teachers_view(request):
    edit_id = request.GET.get('edit')
    editing_teacher = None
    if edit_id:
        editing_teacher = Teacher.objects.filter(id=edit_id).first()

    q_search = request.GET.get('search', '').strip()
    f_dept = request.GET.get('department', '').strip()

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save":
            teacher_id = request.POST.get("teacher_id")
            name = request.POST.get("name", "").strip()
            department = request.POST.get("department", "").strip()

            if teacher_id:
                t = get_object_or_404(Teacher, id=teacher_id)
                t.name = name
                t.department = department
                t.save()
                messages.success(request, f"Дані викладача «{name}» оновлено!")
            else:
                Teacher.objects.create(name=name, department=department)
                messages.success(request, f"Викладача «{name}» додано до бази!")
            return redirect("teachers_list")

        elif action == "delete":
            teacher_id = request.POST.get("teacher_id")
            t = Teacher.objects.filter(id=teacher_id).first()
            if t:
                t.delete()
                messages.success(request, "Викладача видалено з бази!")
            return redirect("teachers_list")

    teachers_qs = Teacher.objects.all()

    if q_search:
        teachers_qs = teachers_qs.filter(name__icontains=q_search)
    if f_dept:
        teachers_qs = teachers_qs.filter(department=f_dept)

    teachers = teachers_qs.order_by("name")
    departments = Teacher.objects.exclude(department="").values_list('department', flat=True).distinct().order_by('department')

    return render(request, "teachers.html", {
        'teachers': teachers,
        'editing_teacher': editing_teacher,
        'departments': departments,
        'q_search': q_search,
        'f_dept': f_dept,
    })

def export_schedule_excel(request):
    current_week = int(request.GET.get('week', 1))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"{current_week} тиждень"

    title_font = Font(name="Segoe UI", size=14, bold=True, color="FFFFFF")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    cell_font = Font(name="Segoe UI", size=10)
    bold_cell_font = Font(name="Segoe UI", size=10, bold=True)
    
    header_fill_color = "DC2626" if current_week == 1 else "16A34A"
    header_fill = PatternFill(start_color=header_fill_color, end_color=header_fill_color, fill_type="solid")
    gray_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    card_fill = PatternFill(start_color="F0F9FF", end_color="F0F9FF", fill_type="solid")
    stream_fill = PatternFill(start_color="FEFCE8", end_color="FEFCE8", fill_type="solid")

    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    ws.merge_cells('A1:F1')
    top_cell = ws['A1']
    top_cell.value = f"Розклад занять — {current_week} тиждень"
    top_cell.font = title_font
    top_cell.fill = header_fill
    top_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 36

    headers = ["Пара", "Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця"]
    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=2, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border
    ws.row_dimensions[2].height = 28

    items = ScheduleItem.objects.filter(week=current_week).select_related('teacher', 'subject', 'room')
    grid = {p: {} for p in range(1, 9)}
    for it in items:
        grid[it.period][it.day] = it

    days_keys = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    for p in range(1, 9):
        row_idx = p + 2
        ws.row_dimensions[row_idx].height = 65

        num_cell = ws.cell(row=row_idx, column=1, value=f"{p} пара")
        num_cell.font = bold_cell_font
        num_cell.fill = gray_fill
        num_cell.alignment = Alignment(horizontal="center", vertical="center")
        num_cell.border = thin_border

        for col_idx, d in enumerate(days_keys, start=2):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

            if d == "Monday" and p == 8:
                cell.value = "—"
                cell.fill = gray_fill
                cell.font = cell_font
            else:
                item = grid[p].get(d)
                if item:
                    room_str = f" [ауд. {item.room.number}]" if item.room else ""
                    if item.is_stream:
                        group_line = f"★ ПОТІК: {item.groups}"
                        cell.fill = stream_fill
                    else:
                        group_line = f"Група: {item.groups}" if item.groups else ""
                        cell.fill = card_fill

                    parts = [item.subject.title, f"{item.teacher.name}{room_str}"]
                    if group_line:
                        parts.append(group_line)

                    cell.value = "\n".join(parts)
                    cell.font = cell_font
                else:
                    cell.value = ""

    ws.column_dimensions['A'].width = 14
    for c in ['B', 'C', 'D', 'E', 'F']:
        ws.column_dimensions[c].width = 34

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="schedule_week_{current_week}.xlsx"'
    wb.save(response)
    return response

def import_schedule_view(request):
    if request.method == "POST":
        file = request.FILES.get("schedule_file")
        if not file:
            messages.error(request, "Оберіть файл для завантаження!")
            return redirect("import_schedule")

        filename = file.name.lower()
        rows_to_process = []

        try:
            if filename.endswith(".xlsx"):
                wb = openpyxl.load_workbook(file)
                sheet = wb.active
                for row in sheet.iter_rows(min_row=2, values_only=True):
                    if any(row):
                        rows_to_process.append([str(c).strip() if c is not None else "" for c in row[:7]])

            elif filename.endswith(".csv"):
                decoded_file = file.read().decode('utf-8-sig')
                io_string = io.StringIO(decoded_file)
                reader = csv.reader(io_string, delimiter=';' if ';' in decoded_file[:200] else ',')
                next(reader, None)
                for row in reader:
                    if any(row):
                        rows_to_process.append([c.strip() for c in row[:7]])
            else:
                messages.error(request, "Формат не підтримується! Завантажте .xlsx або .csv")
                return redirect("import_schedule")

            imported_count = 0
            for r in rows_to_process:
                if len(r) < 5:
                    continue
                week_str, day_raw, period_str, subj_title, teacher_name = r[0], r[1], r[2], r[3], r[4]
                groups = r[5] if len(r) > 5 and r[5] else ""
                room_num = r[6] if len(r) > 6 and r[6] else None

                day_map = {'monday':'Monday','понеділок':'Monday','tuesday':'Tuesday','вівторок':'Tuesday','wednesday':'Wednesday','середа':'Wednesday','thursday':'Thursday','четвер':'Thursday','friday':'Friday',"п'ятниця":'Friday'}
                day = day_map.get(day_raw.lower())
                if not day: continue
                period = int(period_str)
                if day == "Monday" and period > 7: continue

                teacher, _ = Teacher.objects.get_or_create(name=teacher_name)
                subject, _ = Subject.objects.get_or_create(title=subj_title)
                room = Room.objects.get_or_create(number=room_num)[0] if room_num else None

                ScheduleItem.objects.update_or_create(
                    week=int(week_str),
                    day=day,
                    period=period,
                    defaults={'teacher': teacher, 'subject': subject, 'room': room, 'groups': groups}
                )
                imported_count += 1

            if imported_count > 0:
                messages.success(request, f"Успішно імпортовано {imported_count} пар!")
        except Exception as e:
            messages.error(request, f"Помилка: {str(e)}")

        return redirect("import_schedule")

    return render(request, "import.html")
