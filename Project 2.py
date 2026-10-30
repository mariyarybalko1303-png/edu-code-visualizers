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


class CppIterator:
    """Модель C++ ітератора, пов'язана з конкретним масивом/вектором."""
    def __init__(self, container_name, index, is_reverse=False):
        self.container_name = container_name
        self.index = index
        self.is_reverse = is_reverse

    def clone(self):
        return CppIterator(self.container_name, self.index, self.is_reverse)


class CppUniversalEngine:
    """
    Універсальний симулятор коду C++:
    - Бібліотека <iterator>: std::begin, std::end, std::next, std::prev, std::advance, std::distance
    - Операції з ітераторами: ++, --, +=, -=, розіменування *it
    - Range-based for та цикли за ітераторами
    - Бібліотека <array>: std::array<T, N> (fill, at, front, back, swap)
    - Статичні та динамічні масиви (new[], delete[], вказівники)
    - Вектори std::vector (push_back, pop_back, insert, erase, resize, clear)
    - Цикли for та довільні арифметичні вирази
    """
    def __init__(self):
        self.variables = {}
        self.iterators = {}
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

    def resolve_iterator_expr(self, expr_str):
        """Перетворює вирази ітераторів на об'єкт CppIterator або числовий індекс."""
        expr = expr_str.strip()

        # std::next(it, n) / next(it, n)
        next_m = re.match(r"(?:std::)?next\s*\((.*)\)", expr)
        if next_m:
            args = [a.strip() for a in next_m.group(1).split(',')]
            base_it = self.resolve_iterator_expr(args[0])
            offset = self.eval_expression(args[1]) if len(args) > 1 else 1
            if isinstance(base_it, CppIterator):
                res = base_it.clone()
                res.index += (-offset if res.is_reverse else offset)
                return res

        # std::prev(it, n) / prev(it, n)
        prev_m = re.match(r"(?:std::)?prev\s*\((.*)\)", expr)
        if prev_m:
            args = [a.strip() for a in prev_m.group(1).split(',')]
            base_it = self.resolve_iterator_expr(args[0])
            offset = self.eval_expression(args[1]) if len(args) > 1 else 1
            if isinstance(base_it, CppIterator):
                res = base_it.clone()
                res.index -= (-offset if res.is_reverse else offset)
                return res

        # std::begin(c) / begin(c)
        begin_m = re.match(r"(?:std::)?begin\s*\(\s*(\w+)\s*\)", expr)
        if begin_m:
            return CppIterator(begin_m.group(1), 0, False)

        # std::end(c) / end(c)
        end_m = re.match(r"(?:std::)?end\s*\(\s*(\w+)\s*\)", expr)
        if end_m:
            cname = end_m.group(1)
            return CppIterator(cname, len(self.arrays.get(cname, [])), False)

        # std::rbegin(c) / rbegin(c)
        rbegin_m = re.match(r"(?:std::)?rbegin\s*\(\s*(\w+)\s*\)", expr)
        if rbegin_m:
            cname = rbegin_m.group(1)
            return CppIterator(cname, len(self.arrays.get(cname, [])) - 1, True)

        # std::rend(c) / rend(c)
        rend_m = re.match(r"(?:std::)?rend\s*\(\s*(\w+)\s*\)", expr)
        if rend_m:
            return CppIterator(rend_m.group(1), -1, True)

        # c.begin(), c.end(), c.rbegin(), c.rend()
        method_m = re.match(r"(\w+)\.(begin|end|rbegin|rend)\s*\(\s*\)", expr)
        if method_m:
            cname, mname = method_m.group(1), method_m.group(2)
            c_len = len(self.arrays.get(cname, []))
            if mname == "begin": return CppIterator(cname, 0, False)
            if mname == "end": return CppIterator(cname, c_len, False)
            if mname == "rbegin": return CppIterator(cname, c_len - 1, True)
            if mname == "rend": return CppIterator(cname, -1, True)

        # it + n / it - n
        if "+" in expr or "-" in expr:
            op = "+" if "+" in expr else "-"
            parts = expr.split(op, 1)
            left_it = self.resolve_iterator_expr(parts[0])
            if isinstance(left_it, CppIterator):
                offset = self.eval_expression(parts[1])
                res = left_it.clone()
                if op == "+":
                    res.index += (-offset if res.is_reverse else offset)
                else:
                    res.index -= (-offset if res.is_reverse else offset)
                return res

        # Назва існуючої змінної-ітератора
        if expr in self.iterators:
            return self.iterators[expr].clone()

        return None

    def eval_expression(self, expr_str):
        expr = str(expr_str).strip()
        if not expr:
            return 0

        # std::distance(first, last)
        dist_fn = re.search(r"(?:std::)?distance\s*\(([^,]+),\s*([^)]+)\)", expr)
        if dist_fn:
            it1 = self.resolve_iterator_expr(dist_fn.group(1))
            it2 = self.resolve_iterator_expr(dist_fn.group(2))
            if isinstance(it1, CppIterator) and isinstance(it2, CppIterator):
                val_dist = abs(it2.index - it1.index)
                expr = expr.replace(dist_fn.group(0), str(val_dist))

        # Розіменування ітераторів: *it
        for it_name, it_obj in self.iterators.items():
            if it_obj.container_name in self.arrays:
                arr = self.arrays[it_obj.container_name]
                curr_val = arr[it_obj.index] if 0 <= it_obj.index < len(arr) else 0
                expr = re.sub(rf"\*\s*{it_name}\b", str(curr_val), expr)

        # Обробка вказівникової арифметики *(arr + i)
        expr = re.sub(r"\*\s*\(\s*(\w+)\s*\+\s*([^)]+)\)", r"\1[\2]", expr)

        # Обробка .at(index) -> [index]
        expr = re.sub(r"(\w+)\.at\s*\(\s*([^)]+)\)", r"\1[\2]", expr)

        # Обробка .front() та .back()
        for name, arr in self.arrays.items():
            if arr:
                expr = re.sub(rf"\b{name}\.front\s*\(\s*\)", str(arr[0]), expr)
                expr = re.sub(rf"\b{name}\.back\s*\(\s*\)", str(arr[-1]), expr)
            expr = re.sub(rf"\b{name}\.size\s*\(\s*\)", str(len(arr)), expr)
            for idx, val in enumerate(arr):
                expr = re.sub(rf"\b{name}\s*\[\s*{idx}\s*\]", str(val), expr)

        expr = re.sub(r"\brand\s*\(\s*\)", str(random.randint(0, 32767)), expr)
        expr = re.sub(r"\b\w*dist\w*\s*\(\s*\w*\s*\)", f"__random_val()", expr, flags=re.IGNORECASE)

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
        self.iterators.clear()
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

            # 1. Цикл for
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

            # 2. Звичайна інструкція до ';'
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
        # Range-based for: for (auto& x : container) або for (int x : container)
        if ":" in header and ";" not in header:
            var_part, cont_part = [p.strip() for p in header.split(":", 1)]
            var_name = var_part.replace("&", "").split()[-1].strip()
            cont_name = cont_part.strip()
            if cont_name in self.arrays:
                arr = self.arrays[cont_name]
                for idx in range(len(arr)):
                    self.variables[var_name] = arr[idx]
                    self.execute_block(body, steps)
                    # Якщо змінна була по посиланню auto&, зберігаємо зміни
                    if "&" in var_part and self.variables.get(var_name) != arr[idx]:
                        old = arr[idx]
                        arr[idx] = self.variables[var_name]
                        steps.append((list(arr), f"{cont_name}[{idx}] = {arr[idx]} (було {old})"))
            return

        parts = header.split(';')
        if len(parts) != 3:
            return

        init_part, cond_part, inc_part = [p.strip() for p in parts]
        
        # Обробка ініціалізації циклу (звичайна або через ітератор)
        is_iter_loop = False
        loop_iter_name = ""

        if ("iterator" in init_part or "auto" in init_part) and "=" in init_part:
            lhs, rhs = init_part.split('=', 1)
            loop_iter_name = lhs.split()[-1].strip()
            it_obj = self.resolve_iterator_expr(rhs)
            if it_obj:
                self.iterators[loop_iter_name] = it_obj
                is_iter_loop = True
        elif "=" in init_part:
            lhs, rhs = init_part.split('=', 1)
            iter_var = lhs.split()[-1].strip()
            self.variables[iter_var] = self.eval_expression(rhs)

        max_safety_iterations = 60
        it_count = 0

        while it_count < max_safety_iterations:
            # Перевірка умови
            if is_iter_loop and loop_iter_name in self.iterators:
                it_obj = self.iterators[loop_iter_name]
                end_match = re.search(r"!=\s*([^;]+)", cond_part)
                if end_match:
                    target_end = self.resolve_iterator_expr(end_match.group(1))
                    if target_end and it_obj.index == target_end.index:
                        break
            else:
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

            # Виконання тіла циклу
            self.execute_block(body, steps)

            # Інкремент
            if is_iter_loop and loop_iter_name in self.iterators:
                it_obj = self.iterators[loop_iter_name]
                if "++" in inc_part:
                    it_obj.index += (-1 if it_obj.is_reverse else 1)
                elif "--" in inc_part:
                    it_obj.index -= (-1 if it_obj.is_reverse else 1)
            else:
                if "++" in inc_part:
                    vname = inc_part.replace("++", "").strip()
                    self.variables[vname] = self.variables.get(vname, 0) + 1
                elif "--" in inc_part:
                    vname = inc_part.replace("--", "").strip()
                    self.variables[vname] = self.variables.get(vname, 0) - 1
                elif "+=" in inc_part:
                    vname, step_str = inc_part.split("+=", 1)
                    vname = vname.strip()
                    self.variables[vname] = self.variables.get(vname, 0) + self.eval_expression(step_str)

            it_count += 1

    def execute_statement(self, stmt, steps):
        s = " ".join(stmt.split()).strip()
        if not s or s.startswith("cout") or s.startswith("return"):
            return

        # 1. std::advance(it, n)
        advance_m = re.search(r"(?:std::)?advance\s*\(\s*(\w+)\s*,\s*([^)]+)\)", s)
        if advance_m:
            it_name = advance_m.group(1)
            dist = self.eval_expression(advance_m.group(2))
            if it_name in self.iterators:
                it_obj = self.iterators[it_name]
                it_obj.index += (-dist if it_obj.is_reverse else dist)
            return

        # 2. Оголошення та присвоєння ітераторів (vector<int>::iterator it = v.begin(); auto it = ...)
        if ("iterator" in s or "auto" in s) and "=" in s and not ("vector<" in s and "::" not in s):
            lhs, rhs = s.split("=", 1)
            it_name = lhs.split()[-1].strip()
            it_obj = self.resolve_iterator_expr(rhs)
            if it_obj:
                self.iterators[it_name] = it_obj
                return

        # 3. Модифікація через розіменування ітератора: *it = val
        deref_assign = re.match(r"^\*\s*(\w+)\s*=\s*(.+)$", s)
        if deref_assign:
            it_name = deref_assign.group(1)
            val = self.eval_expression(deref_assign.group(2))
            if it_name in self.iterators:
                it_obj = self.iterators[it_name]
                target_name = it_obj.container_name
                if target_name in self.arrays:
                    arr = self.arrays[target_name]
                    idx = it_obj.index
                    if 0 <= idx < len(arr):
                        old = arr[idx]
                        arr[idx] = val
                        steps.append((list(arr), f"{target_name}[{idx}] = {val} (було {old})"))
            return

        # 4. Інкремент / декремент ітератора окремим рядком: it++; ++it; it += n;
        for it_name in list(self.iterators.keys()):
            if re.match(rf"^(\+\+{it_name}|{it_name}\+\+)$", s):
                it_obj = self.iterators[it_name]
                it_obj.index += (-1 if it_obj.is_reverse else 1)
                return
            if re.match(rf"^(--{it_name}|{it_name}--)$", s):
                it_obj = self.iterators[it_name]
                it_obj.index -= (-1 if it_obj.is_reverse else 1)
                return
            if s.startswith(f"{it_name} +="):
                offset = self.eval_expression(s.split("+=", 1)[1])
                it_obj = self.iterators[it_name]
                it_obj.index += (-offset if it_obj.is_reverse else offset)
                return
            if s.startswith(f"{it_name} -="):
                offset = self.eval_expression(s.split("-=", 1)[1])
                it_obj = self.iterators[it_name]
                it_obj.index -= (-offset if it_obj.is_reverse else offset)
                return

        # 5. Оголошення std::array<type, size> name;
        array_lib_m = re.search(r"(?:std\s*::\s*)?array\s*<\s*[\w:]+\s*,\s*([^>]+)>\s*(\w+)", s)
        if array_lib_m:
            raw_sz = array_lib_m.group(1).strip()
            name = array_lib_m.group(2).strip()
            self.main_array_name = name

            sz = min(max(self.eval_expression(raw_sz), 0), 25)
            init_vals = []
            brace_m = re.search(r"\{([^}]*)\}", s)
            if brace_m and brace_m.group(1).strip():
                init_vals = [self.eval_expression(x) for x in brace_m.group(1).split(',') if x.strip()]

            self.arrays[name] = [0] * sz
            for idx, val in enumerate(init_vals[:sz]):
                self.arrays[name][idx] = val

            steps.append((list(self.arrays[name]), f"Оголошено масив: {name}[{sz}]"))
            return

        # 6. delete[] arr;
        delete_m = re.search(r"delete\s*\[\s*\]\s*(\w+)", s)
        if delete_m:
            target_name = delete_m.group(1)
            if target_name in self.arrays:
                self.arrays[target_name].clear()
                steps.append(([], f"{target_name}.clear()"))
            return

        # 7. int* arr = new int[N];
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

        # 8. arr = temp;
        ptr_assign = re.match(r"^(\w+)\s*=\s*(\w+)$", s)
        if ptr_assign:
            lhs = ptr_assign.group(1)
            rhs = ptr_assign.group(2)
            if rhs in self.arrays:
                self.arrays[lhs] = list(self.arrays[rhs])
                self.main_array_name = lhs
                steps.append((list(self.arrays[lhs]), f"Оголошено масив: {lhs}[{len(self.arrays[lhs])}]"))
                return
            elif rhs in self.iterators:
                self.iterators[lhs] = self.iterators[rhs].clone()
                return
            elif rhs in self.variables:
                self.variables[lhs] = self.variables[rhs]
                return

        # 9. vector<int>
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

        # 10. Статичний масив: int arr[N]
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

        # Нормалізація вказівника та методів: *(arr + i) = val -> arr[i] = val
        s = re.sub(r"\*\s*\(\s*(\w+)\s*\+\s*([^)]+)\)\s*=", r"\1[\2] =", s)
        s = re.sub(r"(\w+)\.at\s*\(\s*([^)]+)\)\s*=", r"\1[\2] =", s)
        s = re.sub(r"(\w+)\.front\s*\(\s*\)\s*=", r"\1[0] =", s)

        target_name = self.main_array_name
        for aname in self.arrays:
            if s.startswith(aname + ".") or s.startswith(aname + "["):
                target_name = aname
                break

        if not target_name or target_name not in self.arrays:
            if "=" in s:
                lhs, rhs = s.split("=", 1)
                vname = lhs.replace("*", "").split()[-1].strip()
                it_try = self.resolve_iterator_expr(rhs)
                if it_try:
                    self.iterators[vname] = it_try
                else:
                    self.variables[vname] = self.eval_expression(rhs)
            return

        arr = self.arrays[target_name]

        if f"{target_name}.back()" in s and "=" in s and arr:
            s = s.replace(f"{target_name}.back()", f"{target_name}[{len(arr)-1}]")

        # 11. .fill(val)
        if ".fill" in s:
            val_expr = s[s.find("(")+1:s.rfind(")")]
            val = self.eval_expression(val_expr)
            for i in range(len(arr)):
                old = arr[i]
                arr[i] = val
                steps.append((list(arr), f"{target_name}[{i}] = {val} (було {old})"))
            return

        # 12. .swap(other)
        if ".swap" in s:
            other_m = re.search(r"\.swap\s*\(\s*(\w+)\s*\)", s)
            if other_m:
                other_name = other_m.group(1)
                if other_name in self.arrays:
                    self.arrays[target_name], self.arrays[other_name] = self.arrays[other_name], self.arrays[target_name]
                    steps.append((list(self.arrays[target_name]), f"Оголошено масив: {target_name}[{len(self.arrays[target_name])}]"))
            return

        # 13. push_back / emplace_back
        if ".push_back" in s or ".emplace_back" in s:
            val_expr = s[s.find("(")+1:s.rfind(")")]
            val = self.eval_expression(val_expr)
            if len(arr) < 25:
                arr.append(val)
                steps.append((list(arr), f"{target_name}.push_back({val})"))
            return

        # 14. pop_back
        if ".pop_back" in s:
            if arr:
                rem = arr.pop()
                steps.append((list(arr), f"{target_name}.pop_back(): видалено {rem}"))
            return

        # 15. insert (з підтримкою ітераторів v.insert(it, val) та v.begin() + i)
        if ".insert" in s:
            args_str = s[s.find("(")+1:s.rfind(")")]
            args = [a.strip() for a in args_str.split(",")]
            if len(args) >= 2:
                it_target = self.resolve_iterator_expr(args[0])
                if isinstance(it_target, CppIterator):
                    pos = it_target.index
                else:
                    pos = 0
                    if "+" in args[0]:
                        pos = self.eval_expression(args[0].split("+", 1)[1])
                val = self.eval_expression(args[1])
                pos = max(0, min(pos, len(arr)))
                if len(arr) < 25:
                    arr.insert(pos, val)
                    steps.append((list(arr), f"{target_name}.insert({pos}, {val})"))
            return

        # 16. erase (з підтримкою ітераторів v.erase(it))
        if ".erase" in s:
            arg_str = s[s.find("(")+1:s.rfind(")")].strip()
            it_target = self.resolve_iterator_expr(arg_str)
            if isinstance(it_target, CppIterator):
                pos = it_target.index
            else:
                pos = 0
                if "+" in arg_str:
                    pos = self.eval_expression(arg_str.split("+", 1)[1])
            if 0 <= pos < len(arr):
                rem = arr.pop(pos)
                steps.append((list(arr), f"{target_name}.erase([{pos}]): видалено {rem}"))
            return

        # 17. resize
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

        # 18. clear
        if ".clear" in s:
            arr.clear()
            steps.append(([], f"{target_name}.clear()"))
            return

        # 19. Присвоєння arr[index] = val;
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
