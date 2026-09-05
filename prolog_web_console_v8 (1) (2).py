import os
import tempfile
import webbrowser
from flask import Flask, request, jsonify, render_template_string
from swiplserver import PrologMQI

# Додаємо ваш індивідуальний шлях до SWI-Prolog у змінні оточення скрипта
os.environ["PATH"] += os.pathsep + r"C:\Users\TSS\swipl\bin"

app = Flask(__name__)

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Prolog Web Console</title>
    <!-- Tailwind CSS CDN для гарного стильного інтерфейсу -->
    <script src="https://cdn.tailwindcss.com\"></script>
    <style>
        code, textarea, input, pre { font-family: 'Courier New', Courier, monospace; }
    </style>
</head>
<body class="bg-gray-100 min-h-screen text-gray-800">
    <div class="container mx-auto px-4 py-8 max-w-6xl">
        <header class="mb-8 text-center">
            <h1 class="text-3xl font-bold text-indigo-700 flex items-center justify-center gap-2">
                🧩 Prolog Interactive Web Console
            </h1>
            <p class="text-gray-600 mt-2">Аналог Jupyter Notebook для Prolog на базі Python (Flask + swiplserver)</p>
        </header>

        <div class="grid grid-cols-1 lg:grid-cols-12 gap-8">
            <!-- Ліва колонка: Код та запит -->
            <div class="lg:col-span-7 bg-white p-6 rounded-lg shadow-md border border-gray-200">
                <h2 class="text-xl font-semibold mb-4 text-gray-700 border-b pb-2">📝 Редактор бази знань</h2>
                
                <div class="mb-4">
                    <label class="block text-sm font-medium text-gray-600 mb-2">Правила та факти Prolog:</label>
                    <textarea id="rules" class="w-full h-80 p-3 bg-gray-50 border border-gray-300 rounded font-mono text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none" placeholder="% Введіть правила сюди...">% Підключаємо бібліотеку обмежень clpfd
:- use_module(library(clpfd)).

% Задача про N ферзів
queens(N, Qs) :-
    length(Qs, N),
    Qs ins 1..N,
    all_distinct(Qs),
    safe_queens(Qs).

safe_queens([]).
safe_queens([Q|Qs]) :-
    safe_queens(Qs, Q, 1),
    safe_queens(Qs).

safe_queens([], _, _).
safe_queens([Q|Qs], Q0, D0) :-
    Q0 - Q #\= D0,
    Q - Q0 #\= D0,
    D1 #= D0 + 1,
    safe_queens(Qs, Q0, D1).</textarea>
                </div>

                <div class="mb-6">
                    <label class="block text-sm font-medium text-gray-600 mb-2">Логічний запит (Query):</label>
                    <input type="text" id="query" class="w-full p-3 bg-gray-50 border border-gray-300 rounded font-mono text-sm font-bold text-indigo-900 focus:ring-2 focus:ring-indigo-500 focus:outline-none" value="queens(4, Qs).">
                </div>

                <button id="run-btn" class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-semibold py-3 px-6 rounded-lg shadow-md transition duration-200 flex items-center justify-center gap-2">
                    ▶️ Виконати запит
                </button>
            </div>

            <!-- Права колонка: Результати -->
            <div class="lg:col-span-5 bg-white p-6 rounded-lg shadow-md border border-gray-200 flex flex-col">
                <h2 class="text-xl font-semibold mb-4 text-gray-700 border-b pb-2">📊 Результати обчислень</h2>
                <div id="results-container" class="flex-grow bg-gray-50 border border-gray-200 rounded-lg p-4 min-h-[350px] overflow-auto">
                    <p class="text-gray-500 italic text-center mt-12">Тут з'являться результати логічного виведення...</p>
                </div>
            </div>
        </div>
    </div>

    <script>
        document.getElementById('run-btn').addEventListener('click', async () => {
            const rules = document.getElementById('rules').value;
            const query = document.getElementById('query').value;
            const resultsContainer = document.getElementById('results-container');

            if (!query.trim()) {
                alert('Будь ласка, введіть запит!');
                return;
            }

            resultsContainer.innerHTML = `
                <div class="flex flex-col items-center justify-center h-full mt-12">
                    <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-indigo-600"></div>
                    <span class="ml-3 mt-4 text-gray-600 font-medium">SWI-Prolog обчислює рішення...</span>
                </div>
            `;

            try {
                const response = await fetch('/query', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ rules, query })
                });
                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.error || 'Невідома помилка під час виконання');
                }

                renderResults(data.result);
            } catch (error) {
                resultsContainer.innerHTML = `
                    <div class="bg-red-50 border-l-4 border-red-500 p-4 text-red-700 rounded shadow-sm">
                        <p class="font-bold">🚨 Помилка синтаксису або виконання:</p>
                        <pre class="mt-2 text-xs overflow-x-auto bg-red-100 p-3 rounded font-mono border border-red-200">${error.message}</pre>
                    </div>
                `;
            }
        });

        function renderResults(result) {
            const container = document.getElementById('results-container');
            container.innerHTML = '';

            if (result === true) {
                container.innerHTML = `
                    <div class="bg-green-100 border-l-4 border-green-500 p-4 text-green-800 rounded shadow-sm">
                        <p class="font-bold text-lg">✅ True (Yes)</p>
                        <p class="text-sm mt-1">Prolog підтвердив істинність запиту. Змінних для виведення немає.</p>
                    </div>
                `;
            } else if (result === false) {
                container.innerHTML = `
                    <div class="bg-amber-100 border-l-4 border-amber-500 p-4 text-amber-800 rounded shadow-sm">
                        <p class="font-bold text-lg">❌ False (No)</p>
                        <p class="text-sm mt-1">Prolog не зміг знайти логічних рішень для цього запиту (Fail).</p>
                    </div>
                `;
            } else if (Array.isArray(result)) {
                if (result.length === 0) {
                    container.innerHTML = `
                        <div class="bg-green-100 border-l-4 border-green-500 p-4 text-green-800 rounded shadow-sm">
                            <p class="font-bold text-lg">✅ True (Yes)</p>
                        </div>
                    `;
                } else {
                    // Конвертуємо кожне рішення в класичний рядок Prolog виду: Var = Value
                    const formattedSolutions = result.map(solution => {
                        return Object.entries(solution).map(([variable, val]) => {
                            let formattedVal = val;
                            if (Array.isArray(val)) {
                                // Робимо гарний список із пробілами після ком: [3, 1, 4, 2]
                                formattedVal = `[${val.join(', ')}]`;
                            } else if (typeof val === 'object' && val !== null) {
                                formattedVal = JSON.stringify(val);
                            }
                            return `<span class="text-indigo-700 font-bold">${variable}</span> = <span class="text-green-700">${formattedVal}</span>`;
                        }).join(', ');
                    });

                    // З'єднуємо крапкою з комою (Prolog-стиль) та ставимо крапку в кінці
                    const consoleText = formattedSolutions.join(' ;<br>') + '.';

                    let html = `
                        <div class="mb-4">
                            <p class="text-green-800 font-bold mb-3 text-lg">🎉 Знайдено рішень: ${result.length}</p>
                            
                            <!-- Стилізована під класичний термінал консоль Prolog -->
                            <div class="bg-white text-gray-800 p-4 rounded-lg font-mono text-sm border border-gray-300 shadow-sm overflow-x-auto leading-relaxed">
                                <span class="text-gray-400 select-none">?- </span>${document.getElementById('query').value}<br>
                                ${consoleText}
                            </div>
                        </div>
                    `;
                    container.innerHTML = html;
                }
            }
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/query', methods=['POST'])
def run_query():
    data = request.json
    rules = data.get('rules', '')
    query = data.get('query', '')

    # Створюємо тимчасовий файл для бази знань
    with tempfile.NamedTemporaryFile(suffix=".pl", delete=False, mode="w", encoding="utf-8") as temp_file:
        temp_file.write(rules)
        temp_filepath = temp_file.name

    clean_path = temp_filepath.replace("\\", "/")

    try:
        # Виконуємо запит через swiplserver (Thread-Safe сокет)
        with PrologMQI() as mqi:
            with mqi.create_thread() as prolog_thread:
                prolog_thread.query(f"consult('{clean_path}')")
                result = prolog_thread.query(query)
                return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        # Видаляємо тимчасовий файл
        if os.path.exists(temp_filepath):
            try:
                os.remove(temp_filepath)
            except Exception:
                pass

if __name__ == '__main__':
    print("*" * 60)
    print("Запуск Prolog Interactive Web Console...")
    print("Браузер відкриється автоматично.")
    print("Якщо ні, перейдіть вручну за посиланням: http://127.0.0.1:5000")
    print("*" * 60)
    
    # Автоматично відкриваємо браузер
    webbrowser.open("http://127.0.0.1:5000")
    
    # Запуск Flask без режиму debug, щоб уникнути подвійного запуску потоків і сокетів
    app.run(host="127.0.0.1", port=5000, debug=False)
