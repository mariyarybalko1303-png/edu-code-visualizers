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
        self.base_y = 150.0
        self.active_animation_group = None

        self.metrics_item = None
        self.temp_block = None
        self.temp_label = None

    def reset(self):
        if self.active_animation_group and self.active_animation_group.state() == QParallelAnimationGroup.Running:
            self.active_animation_group.stop()
        self.scene.clear()
        self.current_array_blocks.clear()
        self.static_items.clear()
        self.metrics_item = None
        self.temp_block = None
        self.temp_label = None

    def clear_static_layer(self):
        for item in self.static_items:
            if item.scene() == self.scene:
                self.scene.removeItem(item)
        self.static_items.clear()

    def get_target_pos(self, index):
        return QPointF(self.base_x + index * (self.block_width + self.spacing), self.base_y)

    def update_variables(self, new_values, step_description="", show_sum_avg=False, 
                         count_metric=None, max_indices=None, current_max_val=None, 
                         temp_val=None, pair_indices=None, show_capacity_size=False,
                         capacity_metric=None, size_metric=None, search_index=None, found_index=None):
        self.clear_static_layer()
        
        # 1. Текстовий коментар до кроку
        if step_description:
            desc_item = self.scene.addText(str(step_description))
            desc_item.setFont(QFont("Consolas", 13, QFont.Bold))
            desc_item.setDefaultTextColor(QColor("#2c3e50"))
            desc_item.setPos(self.base_x, self.base_y - 75)
            self.static_items.append(desc_item)

        # 2. Метрики — відображаються контекстно
        metrics_parts = []
        if show_capacity_size:
            cap_str = f"Місткість (Capacity): {capacity_metric}" if capacity_metric is not None else ""
            sz_str = f"Кількість (Size): {size_metric}" if size_metric is not None else f"Кількість (Size): {len(new_values)}"
            joined_cs = " | ".join(filter(None, [cap_str, sz_str]))
            metrics_parts.append(joined_cs)

        if show_sum_avg:
            if new_values:
                curr_sum = sum(new_values)
                curr_avg = curr_sum / len(new_values)
                metrics_parts.append(f"Сума: {curr_sum} | Сер: {curr_avg:.2f}")
            else:
                metrics_parts.append("Сума: 0 | Сер: 0.00")

        if count_metric is not None and not show_capacity_size:
            metrics_parts.append(f"Кількість за умовою: {count_metric}")

        if current_max_val is not None:
            idxs_str = f" [індекси: {', '.join(map(str, max_indices))}]" if max_indices else ""
            metrics_parts.append(f"Максимум (Max): {current_max_val}{idxs_str}")

        if found_index is not None:
            metrics_parts.append(f"Знайдено індекс: {found_index}")

        if metrics_parts:
            metrics_str = "   |   ".join(metrics_parts)
            if not self.metrics_item:
                self.metrics_item = self.scene.addText(metrics_str)
                self.metrics_item.setFont(QFont("Consolas", 11, QFont.Bold))
                self.metrics_item.setDefaultTextColor(QColor("#16a085"))
                self.metrics_item.setPos(self.base_x, self.base_y - 35)
            else:
                self.metrics_item.setPlainText(metrics_str)
                self.metrics_item.setVisible(True)
        else:
            if self.metrics_item:
                self.metrics_item.setVisible(False)

        # 3. Блок буферної змінної temp
        if temp_val is not None:
            temp_pos = QPointF(self.base_x + 40, self.base_y - 125)
            if not self.temp_block:
                self.temp_label = self.scene.addText("temp:")
                self.temp_label.setFont(QFont("Consolas", 11, QFont.Bold))
                self.temp_label.setDefaultTextColor(QColor("#8e44ad"))
                self.temp_label.setPos(self.base_x - 15, self.base_y - 117)

                self.temp_block = AnimatedArrayBlock(
                    text=temp_val, width=self.block_width, height=self.block_height,
                    bg_color="#9b59b6", text_color="#ffffff"
                )
                self.scene.addItem(self.temp_block)
                anim = CartoonAnimationHandler.animate_push_back(self.temp_block, temp_pos)
                anim.start()
            else:
                self.temp_block.set_text(temp_val)
                self.temp_block.set_bg_color("#9b59b6")
                CartoonAnimationHandler.animate_change(self.temp_block, temp_val, "#8e44ad").start()
        else:
            if self.temp_block:
                CartoonAnimationHandler.animate_pop(self.temp_block, self.scene).start()
                self.temp_block = None
            if self.temp_label:
                self.scene.removeItem(self.temp_label)
                self.temp_label = None

        if self.active_animation_group and self.active_animation_group.state() == QParallelAnimationGroup.Running:
            self.active_animation_group.stop()

        anim_group = QParallelAnimationGroup(self)
        old_count = len(self.current_array_blocks)
        new_count = len(new_values)

        min_len = min(old_count, new_count)
        max_idx_set = set(max_indices) if max_indices else set()
        pair_idx_set = set(pair_indices) if pair_indices else set()

        for i in range(min_len):
            block_data = self.current_array_blocks[i]
            block_item = block_data['item']
            old_val = block_data['value']
            new_val = new_values[i]

            # Визначення кольору: пошук знайдено (#2ecc71), поточний елемент пошуку (#f1c40f), пара (#e056fd), максимум (#f39c12)
            if found_index is not None and i == found_index:
                target_color = "#2ecc71"  # Знайдено
            elif search_index is not None and i == search_index:
                target_color = "#f1c40f"  # Сканується зараз зліва направо
            elif i in pair_idx_set:
                target_color = "#e056fd"  # Активна пара сортування/обміну
            elif i in max_idx_set:
                target_color = "#f39c12"  # Максимум
            else:
                target_color = "#33ccff"  # Стандартний блок

            if old_val != new_val:
                block_data['value'] = new_val
                pulse_anim = CartoonAnimationHandler.animate_change(block_item, new_val, target_color)
                anim_group.addAnimation(pulse_anim)
            else:
                block_item.set_bg_color(target_color)

        if new_count > old_count:
            for i in range(old_count, new_count):
                val = new_values[i]
                target_pos = self.get_target_pos(i)
                color = "#2ecc71" if found_index == i else ("#e056fd" if i in pair_idx_set else ("#f39c12" if i in max_idx_set else "#99ff99"))
                new_block = AnimatedArrayBlock(text=val, width=self.block_width, height=self.block_height, bg_color=color)
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
    def __init__(self, container_name, index, is_reverse=False):
        self.container_name = container_name
        self.index = index
        self.is_reverse = is_reverse

    def clone(self):
        return CppIterator(self.container_name, self.index, self.is_reverse)


class CppUniversalEngine:
    """
    Універсальний симулятор коду C++:
    - Лінійний пошук (перегляд зліва направо, std::find, перевірка if (a[i] == target))
    - Бібліотека <algorithm>: std::sort, std::stable_sort, std::reverse, std::max_element, count_if, count
    - Бібліотека <utility>: std::swap
    - Алгоритми сортування: Bubble sort, Selection sort, Insertion sort
    - Відбір за умовою з контролем місткості (capacity) та кількості (size/count)
    - Циклічний зсув ліворуч, буфер temp, ітератори, array, vector
    """
    def __init__(self):
        self.variables = {}
        self.iterators = {}
        self.arrays = {}
        self.main_array_name = "arr"
        self.random_min = 1
        self.random_max = 100
        self.has_sum_avg = False
        self.has_count = False
        self.has_max_search = False
        self.has_capacity_size = False
        self.has_linear_search = False
        self.condition_count = None
        self.max_indices = []
        self.current_max_val = None
        self.temp_val = None
        self.active_pair = None
        self.current_capacity = None
        self.current_size = None
        self.search_index = None
        self.found_index = None
        self.search_target = None

    def clean_code(self, source):
        no_block_comments = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        no_line_comments = re.sub(r"//.*", "", no_block_comments)
        
        normalized = no_line_comments
        normalized = re.sub(r"\bint\s*=\s*", "int temp = ", normalized)
        normalized = re.sub(r"=\s*;\s*$", "= temp;", normalized, flags=re.MULTILINE)
        normalized = re.sub(r"=\s*;\s*", "= temp; ", normalized)

        cleaned_lines = []
        for line in normalized.splitlines():
            l = line.strip()
            if l.startswith("#") or l.startswith("using "):
                continue
            cleaned_lines.append(line)
        return " ".join(cleaned_lines)

    def detect_features(self, code):
        code_lower = code.lower()
        self.has_sum_avg = bool(re.search(r"\b(sum|avg|average|mean|accumulate)\b", code_lower))
        self.has_count = bool(re.search(r"\b(count|counter|matched|count_if)\b", code_lower))
        self.has_max_search = bool(re.search(r"\b(max|maxval|max_val|max_element|maximum)\b", code_lower))
        self.has_capacity_size = bool(re.search(r"\b(capacity|cap|actual_size)\b", code_lower))
        self.has_linear_search = bool(re.search(r"\b(find|search|target|key)\b|==\s*target|target\s*==", code_lower))

    def resolve_iterator_expr(self, expr_str):
        expr = expr_str.strip()

        next_m = re.match(r"(?:std::)?next\s*\((.*)\)", expr)
        if next_m:
            args = [a.strip() for a in next_m.group(1).split(',')]
            base_it = self.resolve_iterator_expr(args[0])
            offset = int(self.eval_expression(args[1])) if len(args) > 1 else 1
            if isinstance(base_it, CppIterator):
                res = base_it.clone()
                res.index += (-offset if res.is_reverse else offset)
                return res

        prev_m = re.match(r"(?:std::)?prev\s*\((.*)\)", expr)
        if prev_m:
            args = [a.strip() for a in prev_m.group(1).split(',')]
            base_it = self.resolve_iterator_expr(args[0])
            offset = int(self.eval_expression(args[1])) if len(args) > 1 else 1
            if isinstance(base_it, CppIterator):
                res = base_it.clone()
                res.index -= (-offset if res.is_reverse else offset)
                return res

        begin_m = re.match(r"(?:std::)?begin\s*\(\s*(\w+)\s*\)", expr)
        if begin_m:
            return CppIterator(begin_m.group(1), 0, False)

        end_m = re.match(r"(?:std::)?end\s*\(\s*(\w+)\s*\)", expr)
        if end_m:
            cname = end_m.group(1)
            return CppIterator(cname, len(self.arrays.get(cname, [])), False)

        rbegin_m = re.match(r"(?:std::)?rbegin\s*\(\s*(\w+)\s*\)", expr)
        if rbegin_m:
            cname = rbegin_m.group(1)
            return CppIterator(cname, len(self.arrays.get(cname, [])) - 1, True)

        rend_m = re.match(r"(?:std::)?rend\s*\(\s*(\w+)\s*\)", expr)
        if rend_m:
            return CppIterator(rend_m.group(1), -1, True)

        method_m = re.match(r"(\w+)\.(begin|end|rbegin|rend)\s*\(\s*\)", expr)
        if method_m:
            cname, mname = method_m.group(1), method_m.group(2)
            c_len = len(self.arrays.get(cname, []))
            if mname == "begin": return CppIterator(cname, 0, False)
            if mname == "end": return CppIterator(cname, c_len, False)
            if mname == "rbegin": return CppIterator(cname, c_len - 1, True)
            if mname == "rend": return CppIterator(cname, -1, True)

        if "+" in expr or "-" in expr:
            op = "+" if "+" in expr else "-"
            parts = expr.split(op, 1)
            left_it = self.resolve_iterator_expr(parts[0])
            if isinstance(left_it, CppIterator):
                offset = int(self.eval_expression(parts[1]))
                res = left_it.clone()
                if op == "+":
                    res.index += (-offset if res.is_reverse else offset)
                else:
                    res.index -= (-offset if res.is_reverse else offset)
                return res

        if expr in self.iterators:
            return self.iterators[expr].clone()

        return None

    def eval_expression(self, expr_str):
        expr = str(expr_str).strip()
        if not expr:
            return 0

        # std::max_element
        max_el_m = re.search(r"(?:std::)?max_element\s*\(([^,]+),\s*([^)]+)\)", expr)
        if max_el_m:
            it1 = self.resolve_iterator_expr(max_el_m.group(1))
            cname = it1.container_name if isinstance(it1, CppIterator) else self.main_array_name
            if cname in self.arrays and self.arrays[cname]:
                arr = self.arrays[cname]
                m_val = max(arr)
                self.current_max_val = m_val
                self.max_indices = [idx for idx, x in enumerate(arr) if x == m_val]
                expr = expr.replace(max_el_m.group(0), str(m_val))

        # std::count_if та std::count
        count_if_m = re.search(r"(?:std::)?count_if\s*\(([^,]+),\s*([^,]+),\s*\[[^\]]*\]\s*\([^\)]*\)\s*\{?\s*return\s*([^;}]+);?\s*\}?\s*\)", expr)
        if count_if_m:
            it1 = self.resolve_iterator_expr(count_if_m.group(1))
            cond_template = count_if_m.group(3).strip()
            cname = it1.container_name if isinstance(it1, CppIterator) else self.main_array_name
            if cname in self.arrays:
                arr = self.arrays[cname]
                matched = 0
                for item in arr:
                    cond_eval = re.sub(r"\b[a-zA-Z_]\w*\b", str(item), cond_template)
                    try:
                        if eval(cond_eval):
                            matched += 1
                    except Exception:
                        pass
                self.condition_count = matched
                expr = expr.replace(count_if_m.group(0), str(matched))

        count_m = re.search(r"(?:std::)?count\s*\(([^,]+),\s*([^,]+),\s*([^)]+)\)", expr)
        if count_m:
            it1 = self.resolve_iterator_expr(count_m.group(1))
            val_to_count = self.eval_expression(count_m.group(3))
            cname = it1.container_name if isinstance(it1, CppIterator) else self.main_array_name
            if cname in self.arrays:
                matched = self.arrays[cname].count(val_to_count)
                self.condition_count = matched
                expr = expr.replace(count_m.group(0), str(matched))

        # std::accumulate
        accum_m = re.search(r"(?:std::)?accumulate\s*\(([^,]+),\s*([^,]+),\s*([^)]+)\)", expr)
        if accum_m:
            it1 = self.resolve_iterator_expr(accum_m.group(1))
            it2 = self.resolve_iterator_expr(accum_m.group(2))
            init_val = self.eval_expression(accum_m.group(3))
            cname = it1.container_name if isinstance(it1, CppIterator) else self.main_array_name
            if cname in self.arrays:
                arr = self.arrays[cname]
                start_i = it1.index if isinstance(it1, CppIterator) else 0
                end_i = it2.index if isinstance(it2, CppIterator) else len(arr)
                sum_val = init_val + sum(arr[start_i:end_i])
                expr = expr.replace(accum_m.group(0), str(sum_val))

        dist_fn = re.search(r"(?:std::)?distance\s*\(([^,]+),\s*([^)]+)\)", expr)
        if dist_fn:
            it1 = self.resolve_iterator_expr(dist_fn.group(1))
            it2 = self.resolve_iterator_expr(dist_fn.group(2))
            if isinstance(it1, CppIterator) and isinstance(it2, CppIterator):
                val_dist = abs(it2.index - it1.index)
                expr = expr.replace(dist_fn.group(0), str(val_dist))

        for it_name, it_obj in self.iterators.items():
            if it_obj.container_name in self.arrays:
                arr = self.arrays[it_obj.container_name]
                curr_val = arr[it_obj.index] if 0 <= it_obj.index < len(arr) else 0
                expr = re.sub(rf"\*\s*{it_name}\b", str(curr_val), expr)

        expr = re.sub(r"\*\s*\(\s*(\w+)\s*\+\s*([^)]+)\)", r"\1[\2]", expr)

        for name, arr in self.arrays.items():
            at_reads = re.findall(rf"\b{name}\.at\s*\(\s*([^)]+)\s*\)", expr)
            for raw_idx in at_reads:
                eval_i = int(self.eval_expression(raw_idx))
                val_at = arr[eval_i] if 0 <= eval_i < len(arr) else 0
                expr = re.sub(rf"\b{name}\.at\s*\(\s*{re.escape(raw_idx)}\s*\)", str(val_at), expr)

        for name, arr in self.arrays.items():
            if arr:
                expr = re.sub(rf"\b{name}\.front\s*\(\s*\)", str(arr[0]), expr)
                expr = re.sub(rf"\b{name}\.back\s*\(\s*\)", str(arr[-1]), expr)
            expr = re.sub(rf"\b{name}\.size\s*\(\s*\)", str(len(arr)), expr)
            expr = re.sub(rf"\b{name}\.capacity\s*\(\s*\)", str(self.current_capacity or len(arr)), expr)
            for idx, val in enumerate(arr):
                expr = re.sub(rf"\b{name}\s*\[\s*{idx}\s*\]", str(val), expr)

        expr = re.sub(r"\(\s*(?:double|float|int)\s*\)", "", expr)
        expr = re.sub(r"static_cast\s*<\s*(?:double|float|int)\s*>\s*\(([^)]+)\)", r"(\1)", expr)

        expr = re.sub(r"\brand\s*\(\s*\)", str(random.randint(0, 32767)), expr)
        expr = re.sub(r"\b\w*dist\w*\s*\(\s*\w*\s*\)", f"__random_val()", expr, flags=re.IGNORECASE)

        env = {
            "__random_val": lambda: random.randint(self.random_min, self.random_max),
            "size_t": int,
            "nullptr": 0,
            "NULL": 0
        }
        env.update(self.variables)

        if self.main_array_name in self.arrays:
            env.setdefault("N", len(self.arrays[self.main_array_name]))
            env.setdefault("n", len(self.arrays[self.main_array_name]))

        try:
            res = eval(expr, {"__builtins__": {}}, env)
            return float(res) if isinstance(res, float) else int(res)
        except Exception:
            if "dist" in expr or "gen" in expr:
                return random.randint(self.random_min, self.random_max)
            return 0

    def run(self, code_text):
        self.variables.clear()
        self.iterators.clear()
        self.arrays.clear()
        self.main_array_name = "arr"
        self.random_min, self.random_max = 1, 100
        self.condition_count = None
        self.max_indices = []
        self.current_max_val = None
        self.temp_val = None
        self.active_pair = None
        self.current_capacity = None
        self.current_size = None
        self.search_index = None
        self.found_index = None
        self.search_target = None
        steps = []

        code = self.clean_code(code_text)
        self.detect_features(code)

        dist_match = re.search(r"uniform_int_distribution\s*(?:<[^>]+>)?\s*\w+\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)", code)
        if dist_match:
            self.random_min = int(dist_match.group(1))
            self.random_max = int(dist_match.group(2))

        main_match = re.search(r"int\s+main\s*\([^)]*\)\s*\{(.*)\}", code, re.DOTALL)
        body = main_match.group(1) if main_match else code

        # Автоматичне виявлення тестового масиву, якщо немає явного оголошення
        has_decl = bool(re.search(r"(?:int|auto|vector|array)\s+\w+\s*\[|\bvector\s*<|\barray\s*<", body))
        if not has_decl and ("a[" in body or "arr[" in body or "sort" in body or "find" in body):
            var_guess = "a" if "a[" in body else "arr"
            self.main_array_name = var_guess
            self.arrays[var_guess] = [12, 45, 7, 23, 89, 56, 31]
            self.variables["N"] = len(self.arrays[var_guess])
            self.variables["n"] = len(self.arrays[var_guess])
            self.current_capacity = len(self.arrays[var_guess])
            self.current_size = len(self.arrays[var_guess])
            steps.append((list(self.arrays[var_guess]), f"Вхідний масив: {var_guess} = [12, 45, 7, 23, 89, 56, 31]", False, None, None, None, None, None, self.has_capacity_size, self.current_capacity, self.current_size, None, None))

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

            if block_str[i:].startswith("if"):
                if_head_match = re.match(r"if\s*\(([^)]*)\)", block_str[i:])
                if if_head_match:
                    condition_str = if_head_match.group(1)
                    i += if_head_match.end()

                    while i < n and block_str[i].isspace():
                        i += 1
                    
                    if i < n and block_str[i] == '{':
                        depth = 1
                        j = i + 1
                        while j < n and depth > 0:
                            if block_str[j] == '{': depth += 1
                            elif block_str[j] == '}': depth -= 1
                            j += 1
                        if_body = block_str[i+1:j-1]
                        i = j
                    else:
                        j = block_str.find(';', i)
                        if_body = block_str[i:j+1] if j != -1 else ""
                        i = j + 1 if j != -1 else n

                    self.run_if_condition(condition_str, if_body, steps)
                    continue

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

    def run_if_condition(self, cond_expr, body_stmt, steps):
        cond_clean = cond_expr
        for k, v in self.variables.items():
            cond_clean = re.sub(rf"\b{k}\b", str(v), cond_clean)
        for name, arr in self.arrays.items():
            cond_clean = re.sub(rf"\b{name}\.size\s*\(\s*\)", str(len(arr)), cond_clean)
            for idx, val in enumerate(arr):
                cond_clean = re.sub(rf"\b{name}\s*\[\s*{idx}\s*\]", str(val), cond_clean)
                cond_clean = re.sub(rf"\b{name}\.at\s*\(\s*{idx}\s*\)", str(val), cond_clean)

        try:
            cond_result = bool(eval(cond_clean))
        except Exception:
            cond_result = False

        curr_arr = list(self.arrays.get(self.main_array_name, []))
        
        # Перевірки типів операцій
        is_search_cond = bool(re.search(r"==\s*target|target\s*==|==\s*key|key\s*==|==\s*\w+", cond_expr) and ("[" in cond_expr or ".at" in cond_expr))
        is_sort_cond = bool(re.search(r"\[.+\]\s*>\s*\[.+\]|\.at\(.+\)\s*>\s*\.at\(.+\)", cond_expr))
        is_max_cond = bool(re.search(r">\s*max|max\s*<", cond_expr.lower()))
        is_filter_cond = bool(re.search(r">\s*0|<\s*0|%\s*2\s*==|!=\s*0|count\s*<|size\s*<|capacity", cond_expr.lower()))

        # Отримуємо поточний індекс пошуку з виразу a[i]
        curr_i = None
        idx_search_match = re.search(r"\[\s*(\w+)\s*\]|\.at\s*\(\s*(\w+)\s*\)", cond_expr)
        if idx_search_match:
            raw_v = idx_search_match.group(1) or idx_search_match.group(2)
            curr_i = self.variables.get(raw_v, None) if not raw_v.isdigit() else int(raw_v)

        if is_search_cond and curr_i is not None and 0 <= curr_i < len(curr_arr):
            self.search_index = curr_i

        if is_sort_cond:
            idxs = [int(self.eval_expression(x)) for x in re.findall(r"\[([^\]]+)\]|\.at\s*\(([^)]+)\)", cond_expr) if x]
            if len(idxs) >= 2:
                self.active_pair = [idxs[0], idxs[1]]

        if cond_result:
            if is_search_cond:
                self.found_index = curr_i
                steps.append((
                    curr_arr, 
                    f"Лінійний пошук: ЕЛЕМЕНТ ЗНАЙДЕНО на позиції [{curr_i}] = {curr_arr[curr_i]}! (break)", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, self.found_index
                ))
            elif is_sort_cond:
                steps.append((
                    curr_arr, 
                    f"Сортування: умова ({cond_expr}) -> ТАК. Потрібен обмін елементів!", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None
                ))
            
            self.execute_block(body_stmt, steps)

            if is_max_cond:
                for k in self.variables:
                    if "max" in k.lower():
                        self.current_max_val = self.variables[k]
                        break
                if self.current_max_val is not None:
                    self.max_indices = [idx for idx, val in enumerate(curr_arr) if val == self.current_max_val]
                steps.append((
                    curr_arr, 
                    f"Знайдено новий максимум: {self.current_max_val} [індекс(и): {', '.join(map(str, self.max_indices))}]", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None
                ))
            elif is_filter_cond:
                cnt_val = self.variables.get("count", self.variables.get("size", self.condition_count))
                self.current_size = cnt_val
                steps.append((
                    curr_arr, 
                    f"Відбір: Умова ({cond_expr}) -> ПІДХОДИТЬ. Елемент відібрано! Кількість: {cnt_val}", 
                    self.has_sum_avg, cnt_val, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None
                ))
        else:
            if is_search_cond:
                val_now = curr_arr[curr_i] if (curr_i is not None and 0 <= curr_i < len(curr_arr)) else ""
                steps.append((
                    curr_arr, 
                    f"Лінійний пошук: перевірка зліва направо [{curr_i}] = {val_now} (не збігається)", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, self.search_index, None
                ))
            elif is_sort_cond:
                steps.append((
                    curr_arr, 
                    f"Сортування: умова ({cond_expr}) -> НІ. Елементи вже впорядковані.", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None
                ))
                self.active_pair = None
            elif is_max_cond:
                steps.append((curr_arr, f"Порівняння: ({cond_expr}) -> Ні (поточний максимум: {self.current_max_val})", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            elif is_filter_cond:
                cnt_val = self.variables.get("count", self.variables.get("size", self.condition_count))
                steps.append((
                    curr_arr, 
                    f"Відбір: Умова ({cond_expr}) -> НЕ підходить (пропущено).", 
                    self.has_sum_avg, cnt_val, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None
                ))

    def run_for_loop(self, header, body, steps):
        if ":" in header and ";" not in header:
            var_part, cont_part = [p.strip() for p in header.split(":", 1)]
            var_name = var_part.replace("&", "").split()[-1].strip()
            cont_name = cont_part.strip()
            if cont_name in self.arrays:
                arr = self.arrays[cont_name]
                for idx in range(len(arr)):
                    self.variables[var_name] = arr[idx]
                    self.execute_block(body, steps)
                    if "&" in var_part and self.variables.get(var_name) != arr[idx]:
                        old = arr[idx]
                        arr[idx] = self.variables[var_name]
                        steps.append((list(arr), f"{cont_name}[{idx}] = {arr[idx]} (було {old})", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

        parts = header.split(';')
        if len(parts) != 3:
            return

        init_part, cond_part, inc_part = [p.strip() for p in parts]
        
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
            self.variables[iter_var] = int(self.eval_expression(rhs))

        max_safety_iterations = 80
        it_count = 0

        while it_count < max_safety_iterations:
            # Перевірка на достроковий вихід (якщо знайдено елемент у лінійному пошуку)
            if self.found_index is not None and "break" in body:
                break

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
                    c_expr = re.sub(rf"\b{name}\.capacity\s*\(\s*\)", str(self.current_capacity or len(arr)), c_expr)
                try:
                    if not eval(c_expr):
                        break
                except Exception:
                    break

            self.execute_block(body, steps)

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
                    self.variables[vname] = self.variables.get(vname, 0) + int(self.eval_expression(step_str))

            it_count += 1

    def execute_statement(self, stmt, steps):
        s = " ".join(stmt.split()).strip()
        if not s or s.startswith("cout") or s.startswith("return"):
            return

        # -------------------------------------------------------------
        # 1. std::find з бібліотеки <algorithm>
        # -------------------------------------------------------------
        find_call = re.match(r"(?:auto\s+(\w+)\s*=)?\s*(?:std::)?find\s*\(([^,]+),\s*([^,]+),\s*([^)]+)\)", s)
        if find_call:
            it1 = self.resolve_iterator_expr(find_call.group(2))
            cname = it1.container_name if isinstance(it1, CppIterator) else self.main_array_name
            target_val = int(self.eval_expression(find_call.group(4)))

            if cname in self.arrays:
                arr = self.arrays[cname]
                steps.append((
                    list(arr), 
                    f"Запуск std::find({cname}): пошук значення {target_val} зліва направо", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None
                ))

                found_pos = None
                for scan_i in range(len(arr)):
                    if arr[scan_i] == target_val:
                        found_pos = scan_i
                        steps.append((
                            list(arr), 
                            f"std::find: ЕЛЕМЕНТ ЗНАЙДЕНО на позиції [{scan_i}] == {target_val}!", 
                            self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                            self.has_capacity_size, self.current_capacity, self.current_size, None, scan_i
                        ))
                        break
                    else:
                        steps.append((
                            list(arr), 
                            f"std::find: сканування [{scan_i}] = {arr[scan_i]} (!= {target_val})", 
                            self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                            self.has_capacity_size, self.current_capacity, self.current_size, scan_i, None
                        ))

                if found_pos is None:
                    steps.append((
                        list(arr), 
                        f"std::find: елемент {target_val} НЕ знайдено (досягнуто end())", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None
                    ))
                return

        # -------------------------------------------------------------
        # 2. std::sort / std::stable_sort
        # -------------------------------------------------------------
        sort_call = re.match(r"(?:std::)?(?:stable_)?sort\s*\(([^)]+)\)", s)
        if sort_call:
            args = [a.strip() for a in sort_call.group(1).split(',')]
            it1 = self.resolve_iterator_expr(args[0])
            cname = it1.container_name if isinstance(it1, CppIterator) else self.main_array_name
            descending = any("greater" in a for a in args)

            if cname in self.arrays:
                arr = self.arrays[cname]
                steps.append((
                    list(arr), 
                    f"Запуск std::sort({cname}) {'(за спаданням)' if descending else '(за зростанням)'}", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None
                ))

                n_len = len(arr)
                for step_i in range(n_len):
                    for step_j in range(0, n_len - step_i - 1):
                        self.active_pair = [step_j, step_j + 1]
                        need_swap = (arr[step_j] < arr[step_j + 1]) if descending else (arr[step_j] > arr[step_j + 1])
                        if need_swap:
                            self.temp_val = arr[step_j]
                            arr[step_j] = arr[step_j + 1]
                            arr[step_j + 1] = self.temp_val
                            steps.append((
                                list(arr), 
                                f"std::sort: обмін {cname}[{step_j}] ({arr[step_j+1]}) <-> {cname}[{step_j+1}] ({arr[step_j]})", 
                                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                                self.has_capacity_size, self.current_capacity, self.current_size, None, None
                            ))
                self.temp_val = None
                self.active_pair = None
                steps.append((
                    list(arr), 
                    f"std::sort({cname}): масив повністю відсортовано!", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None
                ))
                return

        # -------------------------------------------------------------
        # 3. std::swap(a, b)
        # -------------------------------------------------------------
        swap_util = re.match(r"(?:std::)?swap\s*\(([^,]+),\s*([^)]+)\)", s)
        if swap_util:
            arg1, arg2 = swap_util.group(1).strip(), swap_util.group(2).strip()
            idx1_m = re.search(r"(\w+)\s*(?:\[([^\]]+)\]|\.at\s*\(([^)]+)\))", arg1)
            idx2_m = re.search(r"(\w+)\s*(?:\[([^\]]+)\]|\.at\s*\(([^)]+)\))", arg2)

            if idx1_m and idx2_m and idx1_m.group(1) == idx2_m.group(1):
                cname = idx1_m.group(1)
                idx1 = int(self.eval_expression(idx1_m.group(2) or idx1_m.group(3)))
                idx2 = int(self.eval_expression(idx2_m.group(2) or idx2_m.group(3)))

                if cname in self.arrays:
                    arr = self.arrays[cname]
                    if 0 <= idx1 < len(arr) and 0 <= idx2 < len(arr):
                        self.active_pair = [idx1, idx2]
                        self.temp_val = arr[idx1]
                        steps.append((
                            list(arr), 
                            f"std::swap: збережено {cname}[{idx1}] у temp = {self.temp_val}", 
                            self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                            self.has_capacity_size, self.current_capacity, self.current_size, None, None
                        ))
                        arr[idx1] = arr[idx2]
                        arr[idx2] = self.temp_val
                        steps.append((
                            list(arr), 
                            f"std::swap: успішно поміняно місцями [{idx1}] та [{idx2}]", 
                            self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, self.active_pair,
                            self.has_capacity_size, self.current_capacity, self.current_size, None, None
                        ))
                        self.temp_val = None
                        self.active_pair = None
                        return

        # 4. Відбір result[count++] = a[i];
        filter_push = re.search(r"(\w+)\s*\[\s*(\w+)\s*\+\+\s*\]\s*=\s*(.+)", s)
        if filter_push:
            res_arr_name = filter_push.group(1)
            cnt_var_name = filter_push.group(2)
            val_to_add = int(self.eval_expression(filter_push.group(3)))

            if res_arr_name not in self.arrays:
                self.arrays[res_arr_name] = []
            
            self.arrays[res_arr_name].append(val_to_add)
            self.main_array_name = res_arr_name
            self.variables[cnt_var_name] = self.variables.get(cnt_var_name, 0) + 1
            self.current_size = len(self.arrays[res_arr_name])

            steps.append((
                list(self.arrays[res_arr_name]), 
                f"Відбір елемента: {res_arr_name}[{self.current_size - 1}] = {val_to_add} (кількість: {self.current_size})", 
                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                self.has_capacity_size, self.current_capacity, self.current_size, None, None
            ))
            return

        # 5. std::reverse
        reverse_call = re.match(r"(?:std::)?reverse\s*\(([^,]+),\s*([^)]+)\)", s)
        if reverse_call:
            it1 = self.resolve_iterator_expr(reverse_call.group(1))
            it2 = self.resolve_iterator_expr(reverse_call.group(2))
            cname = it1.container_name if isinstance(it1, CppIterator) else self.main_array_name
            if cname in self.arrays:
                arr = self.arrays[cname]
                left = it1.index if isinstance(it1, CppIterator) else 0
                right = (it2.index - 1) if isinstance(it2, CppIterator) else (len(arr) - 1)
                
                steps.append((
                    list(arr), 
                    f"Запуск reverse({cname}): симетричний розворот від [{left}] до [{right}]", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None
                ))

                while left < right:
                    self.active_pair = [left, right]
                    self.temp_val = arr[left]
                    steps.append((
                        list(arr), 
                        f"Реверс: пара [{left}] <-> [{right}]. Збережено temp = {self.temp_val}", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None
                    ))
                    arr[left] = arr[right]
                    steps.append((
                        list(arr), 
                        f"Реверс: {cname}[{left}] = {arr[right]} (копіювання симетричного)", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None
                    ))
                    arr[right] = self.temp_val
                    steps.append((
                        list(arr), 
                        f"Реверс: {cname}[{right}] = temp ({self.temp_val}). Пара успішно обміняна!", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None
                    ))
                    left += 1
                    right -= 1

                self.temp_val = None
                self.active_pair = None
                steps.append((
                    list(arr), 
                    f"Реверс масиву {cname} повністю виконано!", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None
                ))
                return

        # 6. std::advance
        advance_m = re.search(r"(?:std::)?advance\s*\(\s*(\w+)\s*,\s*([^)]+)\)", s)
        if advance_m:
            it_name = advance_m.group(1)
            dist = int(self.eval_expression(advance_m.group(2)))
            if it_name in self.iterators:
                it_obj = self.iterators[it_name]
                it_obj.index += (-dist if it_obj.is_reverse else dist)
            return

        # 7. Ітератори
        if ("iterator" in s or "auto" in s) and "=" in s and not ("vector<" in s and "::" not in s):
            lhs, rhs = s.split("=", 1)
            it_name = lhs.split()[-1].strip()
            it_obj = self.resolve_iterator_expr(rhs)
            if it_obj:
                self.iterators[it_name] = it_obj
                return

        # 8. *it = val
        deref_assign = re.match(r"^\*\s*(\w+)\s*=\s*(.+)$", s)
        if deref_assign:
            it_name = deref_assign.group(1)
            val = int(self.eval_expression(deref_assign.group(2)))
            if it_name in self.iterators:
                it_obj = self.iterators[it_name]
                target_name = it_obj.container_name
                if target_name in self.arrays:
                    arr = self.arrays[target_name]
                    idx = it_obj.index
                    if 0 <= idx < len(arr):
                        old = arr[idx]
                        arr[idx] = val
                        steps.append((list(arr), f"{target_name}[{idx}] = {val} (було {old})", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

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
                offset = int(self.eval_expression(s.split("+=", 1)[1]))
                it_obj = self.iterators[it_name]
                it_obj.index += (-offset if it_obj.is_reverse else offset)
                return
            if s.startswith(f"{it_name} -="):
                offset = int(self.eval_expression(s.split("-=", 1)[1]))
                it_obj = self.iterators[it_name]
                it_obj.index -= (-offset if it_obj.is_reverse else offset)
                return

        # 9. std::array<type, size>
        array_lib_m = re.search(r"(?:std\s*::\s*)?array\s*<\s*[\w:]+\s*,\s*([^>]+)>\s*(\w+)", s)
        if array_lib_m:
            raw_sz = array_lib_m.group(1).strip()
            name = array_lib_m.group(2).strip()
            self.main_array_name = name

            sz = min(max(int(self.eval_expression(raw_sz)), 0), 25)
            init_vals = []
            brace_m = re.search(r"\{([^}]*)\}", s)
            if brace_m and brace_m.group(1).strip():
                init_vals = [int(self.eval_expression(x)) for x in brace_m.group(1).split(',') if x.strip()]

            self.arrays[name] = [0] * sz
            for idx, val in enumerate(init_vals[:sz]):
                self.arrays[name][idx] = val

            self.variables["N"] = sz
            self.variables["n"] = sz
            self.current_capacity = sz
            self.current_size = len(init_vals) if init_vals else sz
            steps.append((list(self.arrays[name]), f"Оголошено std::array: {name}[{sz}]", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

        # 10. delete[] arr;
        delete_m = re.search(r"delete\s*\[\s*\]\s*(\w+)", s)
        if delete_m:
            target_name = delete_m.group(1)
            if target_name in self.arrays:
                self.arrays[target_name].clear()
                self.current_size = 0
                steps.append(([], f"{target_name}.clear()", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

        # 11. new int[N];
        new_m = re.search(r"(?:(?:int|double|float|auto)\s*\*\s*)?(\w+)\s*=\s*new\s+\w+\s*\[([^\]]*)\]", s)
        if new_m:
            name = new_m.group(1)
            raw_sz = new_m.group(2).strip()
            self.main_array_name = name

            init_vals = []
            brace_m = re.search(r"\{([^}]*)\}", s)
            if brace_m and brace_m.group(1).strip():
                init_vals = [int(self.eval_expression(x)) for x in brace_m.group(1).split(',') if x.strip()]

            sz = int(self.eval_expression(raw_sz)) if raw_sz else (len(init_vals) if init_vals else 5)
            sz = min(max(sz, 0), 25)
            self.arrays[name] = [0] * sz
            for idx, val in enumerate(init_vals[:sz]):
                self.arrays[name][idx] = val

            self.variables["N"] = sz
            self.variables["n"] = sz
            self.current_capacity = sz
            self.current_size = len(init_vals) if init_vals else sz
            steps.append((list(self.arrays[name]), f"Оголошено динам. масив: {name}[{sz}]", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

        # 12. arr = temp;
        ptr_assign = re.match(r"^(\w+)\s*=\s*(\w+)$", s)
        if ptr_assign:
            lhs = ptr_assign.group(1)
            rhs = ptr_assign.group(2)
            if rhs in self.arrays:
                self.arrays[lhs] = list(self.arrays[rhs])
                self.main_array_name = lhs
                steps.append((list(self.arrays[lhs]), f"Оголошено масив: {lhs}[{len(self.arrays[lhs])}]", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
                return
            elif rhs in self.iterators:
                self.iterators[lhs] = self.iterators[rhs].clone()
                return
            elif rhs in self.variables:
                self.variables[lhs] = self.variables[rhs]
                return

        # 13. vector<int>
        if "vector<" in s or "std::vector<" in s:
            decl_m = re.search(r"vector\s*<\s*\w+\s*>\s*(\w+)", s)
            if decl_m:
                name = decl_m.group(1)
                self.main_array_name = name
                self.arrays[name] = []

                paren_m = re.search(r"\(([^)]+)\)", s)
                if paren_m:
                    args = [a.strip() for a in paren_m.group(1).split(',')]
                    sz = min(int(self.eval_expression(args[0])), 25)
                    val = int(self.eval_expression(args[1])) if len(args) > 1 else 0
                    self.arrays[name] = [val] * sz
                
                brace_m = re.search(r"\{([^}]+)\}", s)
                if brace_m:
                    self.arrays[name] = [int(self.eval_expression(x)) for x in brace_m.group(1).split(',') if x.strip()][:25]

                self.variables["N"] = len(self.arrays[name])
                self.variables["n"] = len(self.arrays[name])
                self.current_capacity = len(self.arrays[name]) or 10
                self.current_size = len(self.arrays[name])
                steps.append((list(self.arrays[name]), f"Оголошено vector: {name} (розмір {len(self.arrays[name])})", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
                return

        # 14. Класичний масив C: int arr[N] = {...}
        arr_decl = re.search(r"(?:int|auto|double|float)\s+(\w+)\s*\[([^\]]*)\]", s)
        if arr_decl and "=" not in s.split("[")[0]:
            name = arr_decl.group(1)
            raw_sz = arr_decl.group(2).strip()
            self.main_array_name = name

            init_vals = []
            brace_m = re.search(r"\{([^}]*)\}", s)
            if brace_m and brace_m.group(1).strip():
                init_vals = [int(self.eval_expression(x)) for x in brace_m.group(1).split(',') if x.strip()]

            sz = int(self.eval_expression(raw_sz)) if raw_sz else (len(init_vals) if init_vals else 5)
            sz = min(max(sz, 0), 25)
            self.arrays[name] = [0] * sz
            for idx, val in enumerate(init_vals[:sz]):
                self.arrays[name][idx] = val

            self.variables["N"] = sz
            self.variables["n"] = sz
            self.current_capacity = sz
            self.current_size = len(init_vals) if init_vals else sz
            steps.append((list(self.arrays[name]), f"Оголошено масив: {name}[{sz}]", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

        # 15. .at()
        at_assign_m = re.match(r"^(\w+)\.at\s*\(\s*([^)]+)\s*\)\s*=\s*(.+)$", s)
        if at_assign_m:
            target_name = at_assign_m.group(1)
            raw_idx = at_assign_m.group(2)
            raw_val = at_assign_m.group(3)
            idx = int(self.eval_expression(raw_idx))
            val = int(self.eval_expression(raw_val))

            if target_name in self.arrays:
                arr = self.arrays[target_name]
                if 0 <= idx < len(arr):
                    old = arr[idx]
                    arr[idx] = val
                    if "temp" in raw_val.lower():
                        steps.append((list(arr), f"Сортування / Зсув: {target_name}.at({idx}) = temp ({val}) (завершено)", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
                        self.temp_val = None
                    else:
                        steps.append((list(arr), f"{target_name}.at({idx}) = {val} (було {old})", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
                else:
                    steps.append((list(arr), f"std::out_of_range: {target_name}.at({idx}) поза межами", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

        s = re.sub(r"\*\s*\(\s*(\w+)\s*\+\s*([^)]+)\)\s*=", r"\1[\2] =", s)
        s = re.sub(r"(\w+)\.front\s*\(\s*\)\s*=", r"\1[0] =", s)

        # 16. Лічильники count++
        for cnt_alias in ("count", "counter", "matched", "size", "actual_size"):
            if re.match(rf"^(\+\+{cnt_alias}|{cnt_alias}\+\+)$", s):
                self.variables[cnt_alias] = self.variables.get(cnt_alias, 0) + 1
                self.condition_count = self.variables[cnt_alias]
                self.current_size = self.variables[cnt_alias]
                curr_arr = list(self.arrays.get(self.main_array_name, []))
                steps.append((curr_arr, f"Підрахунок: {cnt_alias} = {self.current_size} (+1)", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
                return

        # 17. Сума +=
        plus_eq_m = re.match(r"^(\w+)\s*\+=\s*(.+)$", s)
        if plus_eq_m:
            vname = plus_eq_m.group(1).strip()
            val_add = self.eval_expression(plus_eq_m.group(2))
            self.variables[vname] = self.variables.get(vname, 0) + val_add
            curr_arr = list(self.arrays.get(self.main_array_name, []))
            if "sum" in vname.lower():
                steps.append((curr_arr, f"Накопичення суми: {vname} = {self.variables[vname]} (+{val_add})", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            elif "count" in vname.lower() or "size" in vname.lower():
                self.condition_count = self.variables[vname]
                self.current_size = self.variables[vname]
                steps.append((curr_arr, f"Кількість: {vname} = {self.current_size}", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

        target_name = self.main_array_name
        for aname in self.arrays:
            if s.startswith(aname + ".") or s.startswith(aname + "["):
                target_name = aname
                break

        # 18. Змінні: target, capacity, size, temp, maxVal
        if not target_name or target_name not in self.arrays:
            if "=" in s:
                lhs, rhs = s.split("=", 1)
                vname = lhs.replace("*", "").split()[-1].strip()

                if "target" in vname.lower() or "key" in vname.lower():
                    val_eval = int(self.eval_expression(rhs))
                    self.variables[vname] = val_eval
                    self.search_target = val_eval
                    curr_arr = list(self.arrays.get(self.main_array_name, []))
                    steps.append((
                        curr_arr, 
                        f"Шукане значення для лінійного пошуку: {vname} = {val_eval}", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None
                    ))
                    return

                if "cap" in vname.lower():
                    val_eval = int(self.eval_expression(rhs))
                    self.variables[vname] = val_eval
                    self.current_capacity = val_eval
                    curr_arr = list(self.arrays.get(self.main_array_name, []))
                    steps.append((
                        curr_arr, 
                        f"Визначено місткість (Capacity): {vname} = {val_eval}", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None
                    ))
                    return

                if "temp" in vname.lower():
                    val_eval = self.eval_expression(rhs)
                    self.variables[vname] = val_eval
                    self.temp_val = int(val_eval)
                    curr_arr = list(self.arrays.get(self.main_array_name, []))
                    
                    is_shift_start = bool(re.search(r"\[\s*0\s*\]|\.at\s*\(\s*0\s*\)", rhs))
                    if is_shift_start:
                        steps.append((
                            curr_arr, 
                            f"Циклічний зсув ліворуч: збереження {self.main_array_name}[0] у temp = {self.temp_val}", 
                            self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, [0],
                            self.has_capacity_size, self.current_capacity, self.current_size, None, None
                        ))
                        return

                    idx_match = re.search(r"\[([^\]]+)\]", rhs) or re.search(r"\.at\s*\(([^)]+)\)", rhs)
                    if idx_match:
                        first_i = int(self.eval_expression(idx_match.group(1)))
                        sym_i = len(curr_arr) - 1 - first_i
                        if 0 <= first_i < len(curr_arr) and 0 <= sym_i < len(curr_arr) and first_i != sym_i:
                            self.active_pair = [min(first_i, sym_i), max(first_i, sym_i)]
                            steps.append((
                                curr_arr, 
                                f"Реверс: Симетрична пара [{self.active_pair[0]}] та [{self.active_pair[1]}]. Збережено temp = {self.temp_val}", 
                                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                                self.has_capacity_size, self.current_capacity, self.current_size, None, None
                            ))
                            return

                    steps.append((
                        curr_arr, 
                        f"Обмін / Сортування: збережено temp = {self.temp_val}", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None
                    ))
                    return

                it_try = self.resolve_iterator_expr(rhs)
                if it_try:
                    self.iterators[vname] = it_try
                else:
                    val_eval = self.eval_expression(rhs)
                    self.variables[vname] = val_eval
                    curr_arr = list(self.arrays.get(self.main_array_name, []))

                    if "max" in vname.lower():
                        self.current_max_val = int(val_eval)
                        self.max_indices = [idx for idx, x in enumerate(curr_arr) if x == self.current_max_val]
                        steps.append((
                            curr_arr, 
                            f"Ініціалізація максимуму: {vname} = {self.current_max_val}", 
                            self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                            self.has_capacity_size, self.current_capacity, self.current_size, None, None
                        ))
                    elif "count" in vname.lower() or "matched" in vname.lower() or "size" in vname.lower():
                        self.condition_count = int(val_eval)
                        self.current_size = int(val_eval)
                        steps.append((curr_arr, f"Кількість елементів: {vname} = {self.current_size}", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
                    elif "sum" in vname.lower():
                        steps.append((curr_arr, f"Обчислено суму: {vname} = {val_eval}", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
                    elif "avg" in vname.lower() or "mean" in vname.lower():
                        steps.append((curr_arr, f"Середнє арифметичне: {vname} = {val_eval:.2f}", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

        arr = self.arrays[target_name]

        if f"{target_name}.back()" in s and "=" in s and arr:
            s = s.replace(f"{target_name}.back()", f"{target_name}[{len(arr)-1}]")

        if ".fill" in s:
            val_expr = s[s.find("(")+1:s.rfind(")")]
            val = int(self.eval_expression(val_expr))
            for i in range(len(arr)):
                old = arr[i]
                arr[i] = val
                steps.append((list(arr), f"{target_name}[{i}] = {val} (було {old})", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

        if ".swap" in s:
            other_m = re.search(r"\.swap\s*\(\s*(\w+)\s*\)", s)
            if other_m:
                other_name = other_m.group(1)
                if other_name in self.arrays:
                    self.arrays[target_name], self.arrays[other_name] = self.arrays[other_name], self.arrays[target_name]
                    steps.append((list(self.arrays[target_name]), f"Оголошено масив: {target_name}[{len(self.arrays[target_name])}]", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

        if ".push_back" in s or ".emplace_back" in s:
            val_expr = s[s.find("(")+1:s.rfind(")")]
            val = int(self.eval_expression(val_expr))
            if len(arr) < 25:
                arr.append(val)
                self.current_size = len(arr)
                steps.append((list(arr), f"{target_name}.push_back({val})", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

        if ".pop_back" in s:
            if arr:
                rem = arr.pop()
                self.current_size = len(arr)
                steps.append((list(arr), f"{target_name}.pop_back(): видалено {rem}", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

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
                        pos = int(self.eval_expression(args[0].split("+", 1)[1]))
                val = int(self.eval_expression(args[1]))
                pos = max(0, min(pos, len(arr)))
                if len(arr) < 25:
                    arr.insert(pos, val)
                    self.current_size = len(arr)
                    steps.append((list(arr), f"{target_name}.insert({pos}, {val})", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

        if ".erase" in s:
            arg_str = s[s.find("(")+1:s.rfind(")")].strip()
            it_target = self.resolve_iterator_expr(arg_str)
            if isinstance(it_target, CppIterator):
                pos = it_target.index
            else:
                pos = 0
                if "+" in arg_str:
                    pos = int(self.eval_expression(arg_str.split("+", 1)[1]))
            if 0 <= pos < len(arr):
                rem = arr.pop(pos)
                self.current_size = len(arr)
                steps.append((list(arr), f"{target_name}.erase([{pos}]): видалено {rem}", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

        if ".resize" in s:
            arg_str = s[s.find("(")+1:s.rfind(")")].strip()
            args = [a.strip() for a in arg_str.split(",")]
            new_sz = min(max(int(self.eval_expression(args[0])), 0), 25)
            def_val = int(self.eval_expression(args[1])) if len(args) > 1 else 0
            while len(arr) < new_sz:
                arr.append(def_val)
            while len(arr) > new_sz:
                arr.pop()
            self.current_size = len(arr)
            steps.append((list(arr), f"{target_name}.resize({new_sz})", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

        if ".clear" in s:
            arr.clear()
            self.current_size = 0
            steps.append(([], f"{target_name}.clear()", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None))
            return

        # 19. Присвоєння arr[index] = val; (Сортування, зсув, реверс)
        if ("[" in s and "]" in s and "=" in s) or (".at(" in s and "=" in s):
            if "[" in s:
                lhs, rhs = s.split("=", 1)
                b_l = lhs.find("[")
                b_r = lhs.find("]")
                idx = int(self.eval_expression(lhs[b_l+1:b_r]))
            else:
                lhs, rhs = s.split("=", 1)
                b_l = lhs.find(".at(")
                b_r = lhs.find(")", b_l)
                idx = int(self.eval_expression(lhs[b_l+4:b_r]))
            
            val = int(self.eval_expression(rhs))

            if 0 <= idx < len(arr):
                old = arr[idx]
                arr[idx] = val

                is_shift_step = bool(re.search(r"\[\s*\w+\s*\+\s*1\s*\]|\.at\s*\(\s*\w+\s*\+\s*1\s*\)", rhs))
                is_shift_end = ("temp" in rhs.lower() or rhs.strip() == "") and (idx == len(arr) - 1)

                if is_shift_end:
                    steps.append((
                        list(arr), 
                        f"Циклічний зсув: {target_name}[{idx}] = temp ({val}). Зсув ліворуч завершено!", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, [idx],
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None
                    ))
                    self.temp_val = None
                    self.active_pair = None
                elif is_shift_step:
                    pair = [idx, min(idx + 1, len(arr) - 1)]
                    steps.append((
                        list(arr), 
                        f"Зсув ліворуч: {target_name}[{idx}] = {target_name}[{idx+1}] ({val})", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None
                    ))
                elif "temp" in rhs.lower():
                    steps.append((
                        list(arr), 
                        f"Обмін / Сортування: {target_name}[{idx}] = temp ({val}). Завершено!", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None
                    ))
                    self.temp_val = None
                    self.active_pair = None
                elif ("[" in rhs or ".at(" in rhs) and self.temp_val is not None:
                    steps.append((
                        list(arr), 
                        f"Обмін / Сортування: переміщення {target_name}[{idx}] = {val}", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None
                    ))
                else:
                    steps.append((
                        list(arr), 
                        f"{target_name}[{idx}] = {val} (було {old})", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None
                    ))
            elif idx == len(arr) and len(arr) < 25:
                arr.append(val)
                self.current_size = len(arr)
                steps.append((
                    list(arr), 
                    f"Додано: {target_name}[{idx}] = {val}", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None
                ))
            return


class CodeVisualizer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Покрокова візуалізація масивів C++")

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
            step_data = self.steps_queue[self.current_step]
            arr_state = step_data[0]
            desc = step_data[1]
            show_sum_avg = step_data[2] if len(step_data) > 2 else False
            cnt_metric = step_data[3] if len(step_data) > 3 else None
            max_indices = step_data[4] if len(step_data) > 4 else None
            max_val = step_data[5] if len(step_data) > 5 else None
            temp_val = step_data[6] if len(step_data) > 6 else None
            pair_indices = step_data[7] if len(step_data) > 7 else None
            show_capacity_size = step_data[8] if len(step_data) > 8 else False
            cap_metric = step_data[9] if len(step_data) > 9 else None
            sz_metric = step_data[10] if len(step_data) > 10 else None
            search_idx = step_data[11] if len(step_data) > 11 else None
            found_idx = step_data[12] if len(step_data) > 12 else None

            self.anim_widget.update_variables(
                arr_state, 
                step_description=desc, 
                show_sum_avg=show_sum_avg, 
                count_metric=cnt_metric,
                max_indices=max_indices,
                current_max_val=max_val,
                temp_val=temp_val,
                pair_indices=pair_indices,
                show_capacity_size=show_capacity_size,
                capacity_metric=cap_metric,
                size_metric=sz_metric,
                search_index=search_idx,
                found_index=found_idx
            )
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
