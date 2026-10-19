import os

files = [
    "scheduler/templates/schedule.html",
    "scheduler/templates/student_public_timetable.html",
    "scheduler/templates/teacher_public_timetable.html",
    "scheduler/templates/selective_bachelor.html",
    "scheduler/templates/selective_master.html",
    "scheduler/templates/students.html",
    "scheduler/templates/teachers.html",
    "scheduler/templates/import.html"
]

for path in files:
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        if "selective/bachelor" not in content:
            old = '<a href="/students/" class="sidebar-item">👨‍🎓 Студенти</a>'
            new = '''<a href="/time-table/selective/bachelor/" class="sidebar-item">📚 Вибіркові (Бакалаври)</a>
        <a href="/time-table/selective/master/" class="sidebar-item">📖 Вибіркові (Магістри)</a>
        <a href="/students/" class="sidebar-item">👨‍🎓 Студенти</a>'''
            if old in content:
                content = content.replace(old, new)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"Оновлено: {path}")
print("Готово!")
