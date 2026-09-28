import csv
import io
import openpyxl
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Teacher, Subject, ScheduleItem

DAY_MAPPING = {
    'monday': 'Monday', 'понеділок': 'Monday', 'пн': 'Monday',
    'tuesday': 'Tuesday', 'вівторок': 'Tuesday', 'вт': 'Tuesday',
    'wednesday': 'Wednesday', 'середа': 'Wednesday', 'ср': 'Wednesday',
    'thursday': 'Thursday', 'четвер': 'Thursday', 'чт': 'Thursday',
    'friday': 'Friday', "п'ятниця": 'Friday', 'пт': 'Friday',
}

def schedule_dashboard(request):
    current_week = int(request.GET.get('week', 1))

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add_teacher":
            name = request.POST.get("name", "").strip()
            if name:
                Teacher.objects.create(name=name)
                messages.success(request, f"Викладача «{name}» успішно додано!")
            return redirect(f"/?week={current_week}")

        elif action == "add_subject":
            title = request.POST.get("title", "").strip()
            if title:
                Subject.objects.create(title=title)
                messages.success(request, f"Дисципліну «{title}» успішно додано!")
            return redirect(f"/?week={current_week}")

        elif action == "assign_lesson":
            day = request.POST.get("day")
            period = int(request.POST.get("period"))
            teacher_id = request.POST.get("teacher_id")
            subject_id = request.POST.get("subject_id")
            group_name = request.POST.get("group_name", "314-і").strip()

            if day == "Monday" and period > 7:
                messages.error(request, "У понеділок не може бути 8-ї пари!")
                return redirect(f"/?week={current_week}")

            teacher = Teacher.objects.get(id=teacher_id)
            subject = Subject.objects.get(id=subject_id)

            conflict = ScheduleItem.objects.filter(
                week=current_week, day=day, period=period, teacher=teacher
            ).exists()

            if conflict:
                messages.error(request, f"Колізія: {teacher.name} уже має пару в цей час!")
            else:
                ScheduleItem.objects.update_or_create(
                    week=current_week, day=day, period=period,
                    defaults={'teacher': teacher, 'subject': subject, 'group_name': group_name}
                )
                messages.success(request, f"Пару додано: {subject.title} ({teacher.name})")

            return redirect(f"/?week={current_week}")

    days_order = [
        ("Monday", "Понеділок"),
        ("Tuesday", "Вівторок"),
        ("Wednesday", "Середа"),
        ("Thursday", "Четвер"),
        ("Friday", "П'ятниця")
    ]

    items = ScheduleItem.objects.filter(week=current_week).select_related('teacher', 'subject')
    grid = {p: {} for p in range(1, 9)}
    for it in items:
        grid[it.period][it.day] = it

    context = {
        'current_week': current_week,
        'teachers': Teacher.objects.all(),
        'subjects': Subject.objects.all(),
        'days_order': days_order,
        'periods': range(1, 9),
        'grid': grid
    }
    return render(request, "schedule.html", context)

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
                        rows_to_process.append([str(c).strip() if c is not None else "" for c in row[:6]])

            elif filename.endswith(".csv"):
                decoded_file = file.read().decode('utf-8-sig')
                io_string = io.StringIO(decoded_file)
                reader = csv.reader(io_string, delimiter=';' if ';' in decoded_file[:200] else ',')
                next(reader, None)
                for row in reader:
                    if any(row):
                        rows_to_process.append([c.strip() for c in row[:6]])
            else:
                messages.error(request, "Формат не підтримується! Завантажте .xlsx або .csv")
                return redirect("import_schedule")

            imported_count = 0
            errors = []

            for idx, r in enumerate(rows_to_process, start=2):
                if len(r) < 5:
                    continue

                week_str, day_raw, period_str, subj_title, teacher_name = r[0], r[1], r[2], r[3], r[4]
                group_name = r[5] if len(r) > 5 and r[5] else "314-і"

                try:
                    week = int(week_str)
                    period = int(period_str)
                except ValueError:
                    errors.append(f"Рядок {idx}: неправильний номер тижня/пари ({week_str}, {period_str})")
                    continue

                day = DAY_MAPPING.get(day_raw.lower())
                if not day:
                    errors.append(f"Рядок {idx}: невідомий день тижня «{day_raw}»")
                    continue

                if day == "Monday" and (period < 1 or period > 7):
                    errors.append(f"Рядок {idx}: у понеділок пари тільки 1..7 (вказано {period})")
                    continue

                if day != "Monday" and (period < 1 or period > 8):
                    errors.append(f"Рядок {idx}: для {day_raw} пари мають бути 1..8 (вказано {period})")
                    continue

                teacher, _ = Teacher.objects.get_or_create(name=teacher_name)
                subject, _ = Subject.objects.get_or_create(title=subj_title)

                ScheduleItem.objects.update_or_create(
                    week=week,
                    day=day,
                    period=period,
                    defaults={'teacher': teacher, 'subject': subject, 'group_name': group_name}
                )
                imported_count += 1

            if imported_count > 0:
                messages.success(request, f"Успішно імпортовано {imported_count} пар!")
            for err in errors[:5]:
                messages.warning(request, err)

        except Exception as e:
            messages.error(request, f"Помилка зчитування файлу: {str(e)}")

        return redirect("import_schedule")

    return render(request, "import.html")