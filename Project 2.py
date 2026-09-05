from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QGraphicsView, QGraphicsScene, QGraphicsTextItem
)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QBrush, QColor, QFont, QPen
import sys, re, random


class CodeVisualizer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Покрокова візуалізація масиву")

        main_layout = QHBoxLayout()
        self.setLayout(main_layout)

        # Ліва частина (редактор коду)
        left_layout = QVBoxLayout()
        main_layout.addLayout(left_layout, 1)
        self.code_edit = QTextEdit()
        self.code_edit.setFont(QFont("Consolas", 12))
        
        self.code_edit.textChanged.connect(self.on_code_text_changed)
        left_layout.addWidget(self.code_edit)

        # Кнопка запуску "▶"
        button_layout = QVBoxLayout()
        main_layout.addLayout(button_layout)
        self.run_button = QPushButton("▶")
        self.run_button.setFixedSize(40, 40)
        self.run_button.setFont(QFont("Arial", 14, QFont.Bold))
        self.run_button.clicked.connect(self.run_visualization)
        button_layout.addWidget(self.run_button)
        button_layout.addStretch()

        # Графічна сцена
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        main_layout.addWidget(self.view, 1)

        # Таймер анімації
        self.timer = QTimer()
        self.timer.timeout.connect(self.process_next_step)

        # Стан візуалізації
        self.current_array = []
        self.init_sub_idx = 0
        self.initial_values = []
        self.last_state_array = []
        self.executed_actions = []
        self.action_queue = []
        self.current_y = 50
        self.is_initialized = False
        self.var_name = "nums"
        self.last_var_name = ""

    def on_code_text_changed(self):
        """Якщо поле коду повністю порожнє — очищуємо сцену та скидаємо стан."""
        code = self.code_edit.toPlainText().strip()
        if not code:
            self.reset_visualizer()

    def reset_visualizer(self):
        """Повний скид візуалізатора."""
        self.timer.stop()
        self.scene.clear()
        self.current_array = []
        self.init_sub_idx = 0
        self.initial_values = []
        self.last_state_array = []
        self.executed_actions = []
        self.action_queue = []
        self.current_y = 50
        self.is_initialized = False
        self.last_var_name = ""

    def parse_cpp_code(self):
        """Парсинг масивів, векторів, констант, циклів та операцій."""
        code = self.code_edit.toPlainText()
        code_clean = re.sub(r"//.*", "", code)
        code_clean = re.sub(r"/\*.*?\*/", "", code_clean, flags=re.DOTALL)

        constants = {}
        const_matches = re.findall(r"const\s+int\s+(\w+)\s*(?:=\s*(\d+)|\{\s*(\d+)\s*\}|\(\s*(\d+)\s*\));", code_clean)
        for name, v1, v2, v3 in const_matches:
            constants[name] = int(v1 or v2 or v3)

        initial_values = []
        var_name = "nums"
        declared_size = None

        decl_match = re.search(
            r"(?:vector\s*<\s*\w+\s*>|(?:int|double|float|long|short|char))\s+(\w+)\s*(?:\[\s*(\w+)?\s*\])?\s*(?:=\s*([\{|\(].*?[\}|\)]))?(?:\{([^\}]*)\})?;",
            code_clean,
            re.DOTALL
        )

        if decl_match:
            var_name = decl_match.group(1)
            raw_size = decl_match.group(2)
            init_vals1 = decl_match.group(3)
            init_vals2 = decl_match.group(4)

            if raw_size:
                declared_size = int(raw_size) if raw_size.isdigit() else constants.get(raw_size)

            raw_init = init_vals1 or init_vals2
            if raw_init:
                raw_init = raw_init.strip().strip('{}()').strip()
                if raw_init:
                    items = [x.strip() for x in raw_init.split(',') if x.strip()]
                    parsed = []
                    for item in items:
                        try:
                            parsed.append(float(item) if '.' in item else int(item))
                        except ValueError:
                            parsed.append(0)
                    initial_values = parsed

        if declared_size is not None:
            if not initial_values:
                initial_values = [0] * declared_size
            elif len(initial_values) < declared_size:
                initial_values.extend([0] * (declared_size - len(initial_values)))

        # Цикл for з rand()
        loop_match = re.search(
            r"for\s*\(\s*(?:int\s+|size_t\s+)?\w+\s*(?:=\s*0|\{\s*0\s*\}|;)[^;]*;\s*\w+\s*<\s*(\w+)[^;]*;[^)]+\)\s*\{?([^}]+)\}?",
            code_clean,
            re.DOTALL
        )

        if loop_match:
            limit_str = loop_match.group(1).strip()
            loop_size = constants.get(limit_str, int(limit_str) if limit_str.isdigit() else (declared_size or 5))
            loop_body = loop_match.group(2)

            if "rand()" in loop_body and not self.is_initialized:
                generated = []
                for _ in range(loop_size):
                    offset_mod = re.search(r"([-\d]+)\s*\+\s*rand\s*\(\s*\)\s*%\s*(\d+)", loop_body)
                    mod_offset = re.search(r"rand\s*\(\s*\)\s*%\s*(\d+)\s*([-+])\s*(\d+)", loop_body)
                    mod_match = re.search(r"rand\s*\(\s*\)\s*%\s*(\d+)", loop_body)

                    if offset_mod:
                        generated.append(int(offset_mod.group(1)) + random.randint(0, int(offset_mod.group(2)) - 1))
                    elif mod_offset:
                        mod, op, offset = int(mod_offset.group(1)), mod_offset.group(2), int(mod_offset.group(3))
                        val = random.randint(0, mod - 1)
                        generated.append(val - offset if op == '-' else val + offset)
                    elif mod_match:
                        generated.append(random.randint(0, int(mod_match.group(1)) - 1))
                    else:
                        generated.append(random.randint(1, 100))
                initial_values = generated

        actions = []
        lines = code_clean.split('\n')
        in_loop = False

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            if line_str.startswith("for") or "for (" in line_str:
                in_loop = True
            if in_loop:
                if "}" in line_str:
                    in_loop = False
                continue

            push_match = re.search(r"(\w+)\.(?:push_back|emplace_back)\s*\(\s*([-+]?\d+(?:\.\d+)?)\s*\)\s*;", line_str)
            if push_match:
                val = float(push_match.group(2)) if '.' in push_match.group(2) else int(push_match.group(2))
                actions.append(("push", push_match.group(1), val, line_str))
                continue

            pop_match = re.search(r"(\w+)\.pop_back\s*\(\s*\)\s*;", line_str)
            if pop_match:
                actions.append(("pop", pop_match.group(1), None, line_str))
                continue

            assign_match = re.search(r"(\w+)\s*\[(\d+)\]\s*=\s*([-+]?\d+(?:\.\d+)?)\s*;", line_str)
            if assign_match:
                idx = int(assign_match.group(2))
                val = float(assign_match.group(3)) if '.' in assign_match.group(3) else int(assign_match.group(3))
                actions.append(("set", assign_match.group(1), idx, val, line_str))

        return initial_values, actions, var_name

    def draw_array_block(self, values, start_x, start_y, block_color="#ffcc66", i_index=None):
        if not values:
            return

        block_width = 65
        block_height = 40
        spacing = 5

        total_width = len(values) * block_width + (len(values) - 1) * spacing
        self.scene.addRect(start_x, start_y, total_width, block_height, brush=QBrush(QColor(block_color)))

        if i_index is not None and block_color != "#33ccff":
            text_i = QGraphicsTextItem(f"i={i_index}")
            text_i.setFont(QFont("Arial", 12))
            text_i.setPos(start_x, start_y - block_height - 5)
            self.scene.addItem(text_i)

        x_offset = start_x
        for idx, val in enumerate(values):
            val_str = str(int(val)) if isinstance(val, float) and val.is_integer() else str(val)
            text_val = QGraphicsTextItem(val_str)
            text_val.setFont(QFont("Arial", 12))
            text_val.setPos(x_offset + 12, start_y + 10)
            self.scene.addItem(text_val)

            if idx < len(values) - 1:
                line_x = x_offset + block_width + spacing / 2
                self.scene.addLine(line_x, start_y, line_x, start_y + block_height)
            x_offset += block_width + spacing

    def add_separator(self, y_pos):
        pen = QPen(QColor("#cc6666"), 1.5, Qt.DashLine)
        self.scene.addLine(0, y_pos, 850, y_pos, pen)

    def run_visualization(self):
        code_text = self.code_edit.toPlainText().strip()
        if not code_text:
            self.reset_visualizer()
            return

        self.timer.stop()
        init_vals, current_all_actions, var_name = self.parse_cpp_code()
        self.var_name = var_name

        # Якщо змінили назву змінної або це новий запуск — скидаємо та малюємо з нуля
        if not self.is_initialized or (self.last_var_name and self.last_var_name != var_name):
            self.scene.clear()
            self.current_y = 50
            self.init_sub_idx = 0
            self.initial_values = init_vals
            self.current_array = []
            self.last_state_array = list(init_vals)
            self.executed_actions = []
            self.action_queue = list(current_all_actions)
            self.last_var_name = var_name
            self.is_initialized = True
        else:
            new_actions = []

            # 1. Відстеження прямої зміни всередині списку { ... }
            if init_vals != self.last_state_array:
                if len(init_vals) < len(self.last_state_array):
                    diff_idx = len(init_vals)
                    for i in range(len(init_vals)):
                        if init_vals[i] != self.last_state_array[i]:
                            diff_idx = i
                            break
                    removed_val = self.last_state_array[diff_idx] if diff_idx < len(self.last_state_array) else "?"
                    new_actions.append(("remove_at", self.var_name, diff_idx, removed_val, "remove"))
                
                elif len(init_vals) > len(self.last_state_array):
                    for idx in range(len(self.last_state_array), len(init_vals)):
                        new_actions.append(("push", self.var_name, init_vals[idx], f"add_{idx}"))
                
                else:
                    for idx in range(len(init_vals)):
                        if self.last_state_array[idx] != init_vals[idx]:
                            new_actions.append(("set", self.var_name, idx, init_vals[idx], f"edit_{idx}"))

                self.last_state_array = list(init_vals)

            # 2. Відстеження нових або змінених рядків коду
            for i, act in enumerate(current_all_actions):
                if i >= len(self.executed_actions) or act != self.executed_actions[i]:
                    new_actions.extend(current_all_actions[i:])
                    break

            self.action_queue = new_actions

        if not self.initial_values and not self.action_queue:
            return

        self.timer.start(150)

    def process_next_step(self):
        # 1. Початкова покрокова драбинка
        if self.init_sub_idx < len(self.initial_values):
            sub_vals = self.initial_values[:self.init_sub_idx + 1]
            self.draw_array_block(sub_vals, start_x=0, start_y=self.current_y,
                                  block_color="#ffcc66", i_index=self.init_sub_idx)
            self.current_y += 84
            self.init_sub_idx += 1

            if self.init_sub_idx == len(self.initial_values):
                self.current_array = list(self.initial_values)
                self.current_y += 10
                self.draw_array_block(self.current_array, start_x=50, start_y=self.current_y, block_color="#33ccff")
                self.current_y += 65
                self.add_separator(self.current_y)
                self.current_y += 30
            return

        # 2. Виконання черги операцій
        if self.action_queue:
            action = self.action_queue.pop(0)
            self.executed_actions.append(action)

            action_type = action[0]
            if action_type == "push":
                _, var_name, val, _ = action
                idx = len(self.current_array)
                self.current_array.append(val)
                label_text = f"Додано: {var_name}[{idx}] = {val}"
                text_color = "#00aa00"

            elif action_type == "set":
                _, var_name, idx, val, _ = action
                old_val = self.current_array[idx] if idx < len(self.current_array) else "?"
                if idx < len(self.current_array):
                    self.current_array[idx] = val
                else:
                    self.current_array.append(val)
                label_text = f"Зміна: {var_name}[{idx}] = {old_val} → {val}"
                text_color = "#ff6666"

            elif action_type == "remove_at":
                _, var_name, idx, removed_val, _ = action
                if idx < len(self.current_array):
                    self.current_array.pop(idx)
                label_text = f"Видалено: {var_name}[{idx}] = {removed_val}"
                text_color = "#d35400"

            elif action_type == "pop":
                _, var_name, _, _ = action
                removed = self.current_array.pop() if self.current_array else None
                label_text = f"Видалено останній елемент ({removed})"
                text_color = "#d35400"

            comment_item = QGraphicsTextItem(label_text)
            comment_item.setDefaultTextColor(QColor(text_color))
            comment_item.setFont(QFont("Consolas", 14, QFont.Bold))
            comment_item.setPos(50, self.current_y)
            self.scene.addItem(comment_item)
            self.current_y += 40

            self.draw_array_block(self.current_array, start_x=50, start_y=self.current_y, block_color="#33ccff")
            self.current_y += 65
            self.add_separator(self.current_y)
            self.current_y += 30
        else:
            self.timer.stop()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = CodeVisualizer()
    w.resize(1000, 700)
    w.show()
    sys.exit(app.exec_())