import os
for template in ['selective_bachelor.html', 'selective_master.html', 'selective_postgraduate.html']:
    path = os.path.join('scheduler/templates', template)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        target = '<a href="?edit={{ s.id }}" class="btn-sm" style="background: #0284c7; color: #fff;">Редагувати</a>'
        new_btn = target + '\n                                <a href="/time-table/selective/subject/{{ s.id }}/students/" class="btn-sm" style="background: #16a34a; color: #fff;">Список студентів</a>'
        if 'subject/{{ s.id }}/students/' not in content and target in content:
            content = content.replace(target, new_btn)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Додано кнопку студентів у {template}")
print("Готово!")
