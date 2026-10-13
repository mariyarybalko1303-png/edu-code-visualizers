import sys
import re
import random

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QGraphicsView, QGraphicsScene,
    QGraphicsObject
)
from PyQt5.QtCore import (
    QTimer, Qt, QRectF, QPointF, QPropertyAnimation, QParallelAnimationGroup,
    QSequentialAnimationGroup, QEasingCurve
)
from PyQt5.QtGui import QBrush, QColor, QFont, QPen, QPainter


class AnimatedArrayBlock(QGraphicsObject):
    def __init__(self, text="", width=65.0, height=40.0, 
                 bg_color="#ffcc66", text_color="#000000", parent=None):
        super().__init__(parent)
        self._width = float(width)
        self._height = float(height)
        self._text = str(text)

        self._bg_color = QColor(bg_color)
        self._text_color = QColor(text_color)
        self._border_color = QColor("#333333")
        self._font = QFont("Arial", 12)

    def boundingRect(self):
        pen_width = 1.0
        return QRectF(-pen_width / 2, -pen_width / 2, 
                      self._width + pen_width, self._height + pen_width)

    def paint(self, painter, option, widget=None):
        rect = QRectF(0, 0, self._width, self._height)
        painter.setPen(QPen(self._border_color, 1))
        painter.setBrush(QBrush(self._bg_color))
        painter.drawRect(rect)

        painter.setPen(QPen(self._text_color))
        painter.setFont(self._font)
        painter.drawText(rect, Qt.AlignCenter, self._text)

    def set_bg_color(self, color):
        self._bg_color = QColor(color)
        self.update()

    def set_text_color(self, color):
        self._text_color = QColor(color)
        self.update()

    def set_text(self, text):
        self._text = str(text)
        self.update()


class CartoonAnimationHandler:
    @staticmethod
    def animate_push_back(block_item, target_pos, duration=320):
        block_item.setTransformOriginPoint(block_item.boundingRect().center())
        block_item.setPos(target_pos)
        block_item.setOpacity(1.0)
        block_item.setScale(0.0)

        scale_anim = QPropertyAnimation(block_item, b"scale")
        scale_anim.setDuration(duration)
        scale_anim.setStartValue(0.0)
        scale_anim.setEndValue(1.0)
        scale_anim.setEasingCurve(QEasingCurve.OutBounce)
        return scale_anim

    @staticmethod
    def animate_pop(block_item, scene, duration=300):
        block_item.setTransformOriginPoint(block_item.boundingRect().center())
        group = QParallelAnimationGroup()

        scale_anim = QPropertyAnimation(block_item, b"scale")
        scale_anim.setDuration(duration)
        scale_anim.setStartValue(block_item.scale())
        scale_anim.setEndValue(0.0)
        scale_anim.setEasingCurve(QEasingCurve.InBack)

        opacity_anim = QPropertyAnimation(block_item, b"opacity")
        opacity_anim.setDuration(duration)
        opacity_anim.setStartValue(block_item.opacity())
        opacity_anim.setEndValue(0.0)

        group.addAnimation(scale_anim)
        group.addAnimation(opacity_anim)
        group.finished.connect(lambda: scene.removeItem(block_item) if block_item.scene() else None)
        return group

    @staticmethod
    def animate_change(block_item, new_value, new_bg_color="#ff9999", duration=320):
        block_item.setTransformOriginPoint(block_item.boundingRect().center())
        block_item.set_bg_color(new_bg_color)
        block_item.set_text(new_value)

        seq_group = QSequentialAnimationGroup()
        grow_anim = QPropertyAnimation(block_item, b"scale")
        grow_anim.setDuration(duration // 2)
        grow_anim.setStartValue(1.0)
        grow_anim.setEndValue(1.2)
        grow_anim.setEasingCurve(QEasingCurve.OutQuad)

        shrink_anim = QPropertyAnimation(block_item, b"scale")
        shrink_anim.setDuration(duration // 2)
        shrink_anim.setStartValue(1.2)
        shrink_anim.setEndValue(1.0)
        shrink_anim.setEasingCurve(QEasingCurve.OutBack)

        seq_group.addAnimation(grow_anim)
        seq_group.addAnimation(shrink_anim)
        return seq_group


class AdaptiveAnimationWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self.current_array_blocks = []
        self.static_items = []

        self.block_width = 65.0
        self.block_height = 40.0
        self.spacing = 8.0
        self.base_x = 50.0
        self.base_y = 120.0
        self.active_animation_group = None

    def reset(self):
        if self.active_animation_group and self.active_animation_group.state() == QParallelAnimationGroup.Running:
            self.active_animation_group.stop()
        self.scene.clear()
        self.current_array_blocks.clear()
        self.static_items.clear()

    def clear_static_layer(self):
        for item in self.static_items:
            if item.scene() == self.scene:
                self.scene.removeItem(item)
        self.static_items.clear()

    def get_target_pos(self, index):
        return QPointF(self.base_x + index * (self.block_width + self.spacing), self.base_y)

    def update_variables(self, new_values, step_description=""):
        self.clear_static_layer()
        if step_description:
            desc_item = self.scene.addText(str(step_description))
            desc_item.setFont(QFont("Consolas", 13, QFont.Bold))
            desc_item.setDefaultTextColor(QColor("#2c3e50"))
            desc_item.setPos(self.base_x, self.base_y - 45)
            self.static_items.append(desc_item)

        if self.active_animation_group and self.active_animation_group.state() == QParallelAnimationGroup.Running:
            self.active_animation_group.stop()

        anim_group = QParallelAnimationGroup(self)
        old_count = len(self.current_array_blocks)
        new_count = len(new_values)

        min_len = min(old_count, new_count)
        for i in range(min_len):
            block_data = self.current_array_blocks[i]
            block_item = block_data['item']
            old_val = block_data['value']
            new_val = new_values[i]

            if old_val != new_val:
                block_data['value'] = new_val
                pulse_anim = CartoonAnimationHandler.animate_change(block_item, new_val, "#ff9999")
                anim_group.addAnimation(pulse_anim)
            else:
                block_item.set_bg_color("#33ccff")

        if new_count > old_count:
            for i in range(old_count, new_count):
                val = new_values[i]
                target_pos = self.get_target_pos(i)
                new_block = AnimatedArrayBlock(text=val, width=self.block_width, height=self.block_height, bg_color="#99ff99")
                self.scene.addItem(new_block)
                bounce_anim = CartoonAnimationHandler.animate_push_back(new_block, target_pos)
                anim_group.addAnimation(bounce_anim)
                self.current_array_blocks.append({'item': new_block, 'value': val})

        elif new_count < old_count:
            blocks_to_remove = self.current_array_blocks[new_count:]
            self.current_array_blocks = self.current_array_blocks[:new_count]
            for block_data in blocks_to_remove:
                block_item = block_data['item']
                block_item.set_bg_color("#e74c3c")
                anim_group.addAnimation(CartoonAnimationHandler.animate_pop(block_item, self.scene))

        for i, block_data in enumerate(self.current_array_blocks):
            if i < len(new_values):
                block_data['value'] = new_values[i]
                block_data['item'].set_text(new_values[i])
            target_pos = self.get_target_pos(i)
            if block_data['item'].pos() != target_pos:
                block_data['item'].setPos(target_pos)

        self.active_animation_group = anim_group
        anim_group.start()


class CppUniversalEngine:
    """
    Універсальний симулятор коду C++:
    - Звичайні фіксовані масиви
    - Динамічні масиви (new[], delete[], вказівники та їх переприсвоєння)
    - Вектори std::vector (push_back, pop_back, insert, erase, resize, clear)
    - Цикли for та арифметичні вирази
    """
    def __init__(self):
        self.variables = {}
        self.arrays = {}
        self.main_array_name = "arr"
        self.random_min = 1
        self.random_max = 100

    def clean_code(self, source):
        no_block_comments = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        no_line_comments = re.sub(r"//.*", "", no_block_comments)
        
        cleaned_lines = []
        for line in no_line_comments.splitlines():
            l = line.strip()
            if l.startswith("#") or l.startswith("using "):
                continue
            cleaned_lines.append(line)
        return " ".join(cleaned_lines)

    def eval_expression(self, expr_str):
        expr = str(expr_str).strip()
        if not expr:
            return 0

        # Нормалізація вказівникової арифметики *(arr + i) -> arr[i]
        expr = re.sub(r"\*\s*\(\s*(\w+)\s*\+\s*([^)]+)\)", r"\1[\2]", expr)

        expr = re.sub(r"\brand\s*\(\s*\)", str(random.randint(0, 32767)), expr)
        expr = re.sub(r"\b\w*dist\w*\s*\(\s*\w*\s*\)", f"__random_val()", expr, flags=re.IGNORECASE)

        for name, arr in self.arrays.items():
            expr = re.sub(rf"\b{name}\.size\s*\(\s*\)", str(len(arr)), expr)
            for idx, val in enumerate(arr):
                expr = re.sub(rf"\b{name}\s*\[\s*{idx}\s*\]", str(val), expr)

        env = {
            "__random_val": lambda: random.randint(self.random_min, self.random_max),
            "size_t": int,
            "nullptr": 0,
            "NULL": 0
        }
        env.update(self.variables)

        try:
            return int(eval(expr, {"__builtins__": {}}, env))
        except Exception:
            if "dist" in expr or "gen" in expr:
                return random.randint(self.random_min, self.random_max)
            return 0

    def run(self, code_text):
        self.variables.clear()
        self.arrays.clear()
        self.main_array_name = ""
        self.random_min, self.random_max = 1, 100
        steps = []

        code = self.clean_code(code_text)

        dist_match = re.search(r"uniform_int_distribution\s*(?:<[^>]+>)?\s*\w+\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)", code)
        if dist_match:
            self.random_min = int(dist_match.group(1))
            self.random_max = int(dist_match.group(2))

        main_match = re.search(r"int\s+main\s*\([^)]*\)\s*\{(.*)\}", code, re.DOTALL)
        body = main_match.group(1) if main_match else code

        self.execute_block(body, steps)
        return steps

    def execute_block(self, block_str, steps):
        i = 0
        n = len(block_str)

        while i < n:
            while i < n and block_str[i].isspace():
                i += 1
            if i >= n:
                break

            # Цикл for(...) { ... }
            if block_str[i:].startswith("for"):
                for_head_match = re.match(r"for\s*\(([^)]*)\)", block_str[i:])
                if for_head_match:
                    header = for_head_match.group(1)
                    i += for_head_match.end()

                    while i < n and block_str[i].isspace():
                        i += 1
                    
                    if i < n and block_str[i] == '{':
                        depth = 1
                        j = i + 1
                        while j < n and depth > 0:
                            if block_str[j] == '{': depth += 1
                            elif block_str[j] == '}': depth -= 1
                            j += 1
                        body_stmt = block_str[i+1:j-1]
                        i = j
                    else:
                        j = block_str.find(';', i)
                        body_stmt = block_str[i:j+1] if j != -1 else ""
                        i = j + 1 if j != -1 else n

                    self.run_for_loop(header, body_stmt, steps)
                    continue

            semi_pos = block_str.find(';', i)
            if semi_pos == -1:
                stmt = block_str[i:].strip()
                i = n
            else:
                stmt = block_str[i:semi_pos].strip()
                i = semi_pos + 1

            if stmt:
                self.execute_statement(stmt, steps)

    def run_for_loop(self, header, body, steps):
        parts = header.split(';')
        if len(parts) != 3:
            return

        init_part, cond_part, inc_part = [p.strip() for p in parts]
        
        iter_var = "i"
        if "=" in init_part:
            lhs, rhs = init_part.split('=', 1)
            iter_var = lhs.split()[-1].strip()
            self.variables[iter_var] = self.eval_expression(rhs)

        max_safety_iterations = 60
        it_count = 0

        while it_count < max_safety_iterations:
            c_expr = cond_part
            for k, v in self.variables.items():
                c_expr = re.sub(rf"\b{k}\b", str(v), c_expr)
            for name, arr in self.arrays.items():
                c_expr = re.sub(rf"\b{name}\.size\s*\(\s*\)", str(len(arr)), c_expr)

            try:
                if not eval(c_expr):
                    break
            except Exception:
                break

            self.execute_block(body, steps)

            if "++" in inc_part:
                self.variables[iter_var] = self.variables.get(iter_var, 0) + 1
            elif "--" in inc_part:
                self.variables[iter_var] = self.variables.get(iter_var, 0) - 1
            elif "+=" in inc_part:
                step_val = self.eval_expression(inc_part.split("+=", 1)[1])
                self.variables[iter_var] = self.variables.get(iter_var, 0) + step_val
            
            it_count += 1

    def execute_statement(self, stmt, steps):
        s = " ".join(stmt.split()).strip()
        if not s or s.startswith("cout") or s.startswith("return"):
            return

        # 1. Звільнення пам'яті динамічного масиву: delete[] arr;
        delete_m = re.search(r"delete\s*\[\s*\]\s*(\w+)", s)
        if delete_m:
            target_name = delete_m.group(1)
            if target_name in self.arrays:
                self.arrays[target_name].clear()
                steps.append(([], f"{target_name}.clear()"))
            return

        # 2. Оголошення або виділення динамічного масиву: int* arr = new int[N]...
        new_m = re.search(r"(?:(?:int|double|float|auto)\s*\*\s*)?(\w+)\s*=\s*new\s+\w+\s*\[([^\]]*)\]", s)
        if new_m:
            name = new_m.group(1)
            raw_sz = new_m.group(2).strip()
            self.main_array_name = name

            init_vals = []
            brace_m = re.search(r"\{([^}]*)\}", s)
            if brace_m and brace_m.group(1).strip():
                init_vals = [self.eval_expression(x) for x in brace_m.group(1).split(',') if x.strip()]

            sz = self.eval_expression(raw_sz) if raw_sz else (len(init_vals) if init_vals else 5)
            sz = min(max(sz, 0), 25)
            self.arrays[name] = [0] * sz
            for idx, val in enumerate(init_vals[:sz]):
                self.arrays[name][idx] = val

            steps.append((list(self.arrays[name]), f"Оголошено масив: {name}[{sz}]"))
            return

        # 3. Переприсвоєння вказівника на інший динамічний масив: arr = temp;
        ptr_assign = re.match(r"^(\w+)\s*=\s*(\w+)$", s)
        if ptr_assign:
            lhs = ptr_assign.group(1)
            rhs = ptr_assign.group(2)
            if rhs in self.arrays:
                self.arrays[lhs] = list(self.arrays[rhs])
                self.main_array_name = lhs
                steps.append((list(self.arrays[lhs]), f"Оголошено масив: {lhs}[{len(self.arrays[lhs])}]"))
                return
            elif rhs in self.variables:
                self.variables[lhs] = self.variables[rhs]
                return

        # 4. Оголошення vector<int> name ...
        if "vector<" in s or "std::vector<" in s:
            decl_m = re.search(r"vector\s*<\s*\w+\s*>\s*(\w+)", s)
            if decl_m:
                name = decl_m.group(1)
                self.main_array_name = name
                self.arrays[name] = []

                paren_m = re.search(r"\(([^)]+)\)", s)
                if paren_m:
                    args = [a.strip() for a in paren_m.group(1).split(',')]
                    sz = min(self.eval_expression(args[0]), 25)
                    val = self.eval_expression(args[1]) if len(args) > 1 else 0
                    self.arrays[name] = [val] * sz
                
                brace_m = re.search(r"\{([^}]+)\}", s)
                if brace_m:
                    self.arrays[name] = [self.eval_expression(x) for x in brace_m.group(1).split(',') if x.strip()][:25]

                steps.append((list(self.arrays[name]), f"Оголошено vector: {name} (розмір {len(self.arrays[name])})"))
                return

        # 5. Оголошення статичного масиву C: int arr[N]...
        arr_decl = re.search(r"(?:int|auto|double|float)\s+(\w+)\s*\[([^\]]*)\]", s)
        if arr_decl and "=" not in s.split("[")[0]:
            name = arr_decl.group(1)
            raw_sz = arr_decl.group(2).strip()
            self.main_array_name = name

            init_vals = []
            brace_m = re.search(r"\{([^}]*)\}", s)
            if brace_m and brace_m.group(1).strip():
                init_vals = [self.eval_expression(x) for x in brace_m.group(1).split(',') if x.strip()]

            sz = self.eval_expression(raw_sz) if raw_sz else (len(init_vals) if init_vals else 5)
            sz = min(max(sz, 0), 25)
            self.arrays[name] = [0] * sz
            for idx, val in enumerate(init_vals[:sz]):
                self.arrays[name][idx] = val

            steps.append((list(self.arrays[name]), f"Оголошено масив: {name}[{sz}]"))
            return

        # Нормалізація присвоєння через вказівник: *(arr + i) = val -> arr[i] = val
        s = re.sub(r"\*\s*\(\s*(\w+)\s*\+\s*([^)]+)\)\s*=", r"\1[\2] =", s)

        target_name = self.main_array_name
        for aname in self.arrays:
            if s.startswith(aname + ".") or s.startswith(aname + "["):
                target_name = aname
                break

        if not target_name or target_name not in self.arrays:
            if "=" in s:
                lhs, rhs = s.split("=", 1)
                vname = lhs.replace("*", "").split()[-1].strip()
                self.variables[vname] = self.eval_expression(rhs)
            return

        arr = self.arrays[target_name]

        # 6. push_back / emplace_back
        if ".push_back" in s or ".emplace_back" in s:
            val_expr = s[s.find("(")+1:s.rfind(")")]
            val = self.eval_expression(val_expr)
            if len(arr) < 25:
                arr.append(val)
                steps.append((list(arr), f"{target_name}.push_back({val})"))
            return

        # 7. pop_back
        if ".pop_back" in s:
            if arr:
                rem = arr.pop()
                steps.append((list(arr), f"{target_name}.pop_back(): видалено {rem}"))
            return

        # 8. insert (begin() + pos, val)
        if ".insert" in s:
            args_str = s[s.find("(")+1:s.rfind(")")]
            args = [a.strip() for a in args_str.split(",")]
            if len(args) >= 2:
                pos = 0
                if "+" in args[0]:
                    pos = self.eval_expression(args[0].split("+", 1)[1])
                val = self.eval_expression(args[1])
                pos = max(0, min(pos, len(arr)))
                if len(arr) < 25:
                    arr.insert(pos, val)
                    steps.append((list(arr), f"{target_name}.insert({pos}, {val})"))
            return

        # 9. erase (begin() + pos)
        if ".erase" in s:
            arg_str = s[s.find("(")+1:s.rfind(")")].strip()
            pos = 0
            if "+" in arg_str:
                pos = self.eval_expression(arg_str.split("+", 1)[1])
            if 0 <= pos < len(arr):
                rem = arr.pop(pos)
                steps.append((list(arr), f"{target_name}.erase([{pos}]): видалено {rem}"))
            return

        # 10. resize
        if ".resize" in s:
            arg_str = s[s.find("(")+1:s.rfind(")")].strip()
            args = [a.strip() for a in arg_str.split(",")]
            new_sz = min(max(self.eval_expression(args[0]), 0), 25)
            def_val = self.eval_expression(args[1]) if len(args) > 1 else 0
            while len(arr) < new_sz:
                arr.append(def_val)
            while len(arr) > new_sz:
                arr.pop()
            steps.append((list(arr), f"{target_name}.resize({new_sz})"))
            return

        # 11. clear
        if ".clear" in s:
            arr.clear()
            steps.append(([], f"{target_name}.clear()"))
            return

        # 12. Присвоєння arr[index] = val;
        if "[" in s and "]" in s and "=" in s:
            lhs, rhs = s.split("=", 1)
            b_l = lhs.find("[")
            b_r = lhs.find("]")
            idx = self.eval_expression(lhs[b_l+1:b_r])
            val = self.eval_expression(rhs)

            if 0 <= idx < len(arr):
                old = arr[idx]
                arr[idx] = val
                steps.append((list(arr), f"{target_name}[{idx}] = {val} (було {old})"))
            elif idx == len(arr) and len(arr) < 25:
                arr.append(val)
                steps.append((list(arr), f"{target_name}[{idx}] = {val}"))
            return


class CodeVisualizer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Покрокова візуалізація масивів і векторів C++")

        main_layout = QHBoxLayout()
        self.setLayout(main_layout)

        left_layout = QVBoxLayout()
        main_layout.addLayout(left_layout, 1)
        self.code_edit = QTextEdit()
        self.code_edit.setFont(QFont("Consolas", 12))
        self.code_edit.textChanged.connect(self.on_code_text_changed)
        left_layout.addWidget(self.code_edit)

        button_layout = QVBoxLayout()
        main_layout.addLayout(button_layout)
        
        self.run_button = QPushButton("▶")
        self.run_button.setFixedSize(42, 42)
        self.run_button.setFont(QFont("Arial", 14, QFont.Bold))
        self.run_button.clicked.connect(self.run_visualization)
        button_layout.addWidget(self.run_button)

        self.stop_button = QPushButton("⏹")
        self.stop_button.setFixedSize(42, 42)
        self.stop_button.setFont(QFont("Arial", 14, QFont.Bold))
        self.stop_button.setToolTip("Скинути стан")
        self.stop_button.clicked.connect(self.reset_visualizer)
        button_layout.addWidget(self.stop_button)

        button_layout.addStretch()

        self.anim_widget = AdaptiveAnimationWidget(self)
        main_layout.addWidget(self.anim_widget, 1)

        self.timer = QTimer()
        self.timer.timeout.connect(self.process_next_step)

        self.steps_queue = []
        self.current_step = 0
        self.engine = CppUniversalEngine()

    def on_code_text_changed(self):
        if not self.code_edit.toPlainText().strip():
            self.reset_visualizer()

    def reset_visualizer(self):
        self.timer.stop()
        self.anim_widget.reset()
        self.steps_queue = []
        self.current_step = 0

    def run_visualization(self):
        code_text = self.code_edit.toPlainText().strip()
        if not code_text:
            self.reset_visualizer()
            return

        self.timer.stop()
        self.anim_widget.reset()
        self.current_step = 0

        self.steps_queue = self.engine.run(code_text)

        if not self.steps_queue:
            return

        self.timer.start(400)

    def process_next_step(self):
        if self.current_step < len(self.steps_queue):
            arr_state, desc = self.steps_queue[self.current_step]
            self.anim_widget.update_variables(arr_state, step_description=desc)
            self.current_step += 1
        else:
            self.timer.stop()


if __name__ == "__main__":
    app = QApplication.instance()
    is_jupyter = app is not None
    if app is None:
        app = QApplication(sys.argv)

    window = CodeVisualizer()
    window.resize(1050, 700)
    window.show()

    if not is_jupyter:
        sys.exit(app.exec_())
