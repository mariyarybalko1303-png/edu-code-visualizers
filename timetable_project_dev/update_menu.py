import os

target_str = '<a href="/time-table/selective/master/" class="sidebar-item">📖 Вибіркові (Магістри)</a>'
new_str = target_str + '\n        <a href="/time-table/selective/postgraduate/" class="sidebar-item">🎓 Вибіркові (Аспіранти)</a>'

for root, dirs, files in os.walk('scheduler/templates'):
    for file in files:
        if file.endswith('.html'):
            path = os.path.join(root, file)
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()

            if 'selective/postgraduate' not in content and target_str in content:
                content = content.replace(target_str, new_str)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"Оновлено: {file}")

print("Готово!")
