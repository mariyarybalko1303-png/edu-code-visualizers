path = "scheduler/templates/student_public_timetable.html"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

target = '<button type="submit">Показати розклад</button>'
btn = '''<button type="submit">Показати розклад</button>
        {% if group_to_show %}
        <a href="/export/group/?group={{ group_to_show }}&week={{ current_week }}" style="display: inline-block; background: #16a34a; color: #fff; padding: 9px 18px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 13px; margin-left: 10px;">📥 Завантажити Excel (група {{ group_to_show }})</a>
        {% endif %}'''

if "export/group" not in content:
    content = content.replace(target, btn)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Кнопку успішно додано!")
else:
    print("Кнопка вже була додана раніше.")
