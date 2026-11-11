import sys
import re
import random

from PyQt5.QtWidgets import (
    QComboBox,
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QGraphicsView, QGraphicsScene,
    QGraphicsObject, QLabel, QSlider, QGroupBox, QSplitter
)
from PyQt5.QtCore import (
    QTimer, Qt, QRectF, QPointF, QPropertyAnimation, QParallelAnimationGroup,
    QSequentialAnimationGroup, QEasingCurve
)
from PyQt5.QtGui import QBrush, QColor, QFont, QPen, QPainter


class AnimatedArrayBlock(QGraphicsObject):
    """Графічний елемент комірки масиву з підтримкою виділення рамки, кольору та текстових значень."""
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
        painter.setRenderHint(QPainter.Antialiasing)
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
    """Обробник плавної анімації появи, видалення та пульсації блоків із налаштовуваною тривалістю."""
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
        grow_anim.setDuration(max(10, duration // 2))
        grow_anim.setStartValue(1.0)
        grow_anim.setEndValue(1.2)
        grow_anim.setEasingCurve(QEasingCurve.OutQuad)

        shrink_anim = QPropertyAnimation(block_item, b"scale")
        shrink_anim.setDuration(max(10, duration // 2))
        shrink_anim.setStartValue(1.2)
        shrink_anim.setEndValue(1.0)
        shrink_anim.setEasingCurve(QEasingCurve.OutBack)

        seq_group.addAnimation(grow_anim)
        seq_group.addAnimation(shrink_anim)
        return seq_group


class AdaptiveAnimationWidget(QWidget):
    """Графічна сцена візуалізації з одночасним відображенням багатьох масивів, синхронізацією анімацій та метрик."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self.array_rows = {}  # { arr_name: {'label': text_item, 'blocks': [{'item': block, 'value': val}, ...]} }
        self.static_items = []

        self.block_width = 65.0
        self.block_height = 40.0
        self.spacing = 8.0
        self.base_x = 75.0
        self.base_y = 150.0
        self.active_animation_group = None
        self.anim_duration = 300

        self.metrics_item = None
        self.temp_block = None
        self.temp_label = None

    def set_animation_speed(self, step_interval_ms):
        """Адаптація тривалості анімації під інтервал таймера відтворення."""
        self.anim_duration = max(80, int(step_interval_ms * 0.75))

    def reset(self):
        if self.active_animation_group and self.active_animation_group.state() == QParallelAnimationGroup.Running:
            self.active_animation_group.stop()
        self.scene.clear()
        self.array_rows.clear()
        self.static_items.clear()
        self.metrics_item = None
        self.temp_block = None
        self.temp_label = None

    def clear_static_layer(self):
        for item in self.static_items:
            if item.scene() == self.scene:
                self.scene.removeItem(item)
        self.static_items.clear()

    def get_target_pos(self, index, row_idx=0):
        row_y = self.base_y + row_idx * (self.block_height + 45.0)
        return QPointF(self.base_x + index * (self.block_width + self.spacing), row_y)

    def finalize_running_animations(self):
        """Завершення активних анімацій перед початком нового кроку для уникнення «стрибків» блоків."""
        if self.active_animation_group and self.active_animation_group.state() == QParallelAnimationGroup.Running:
            self.active_animation_group.stop()
        for row_data in self.array_rows.values():
            for block_data in row_data['blocks']:
                item = block_data['item']
                item.setScale(1.0)
                item.setOpacity(1.0)

    def update_variables(self, new_values, step_description="", show_sum_avg=False, 
                         count_metric=None, max_indices=None, current_max_val=None, 
                         temp_val=None, pair_indices=None, show_capacity_size=False,
                         capacity_metric=None, size_metric=None, search_index=None, 
                         found_index=None, binary_range=None, binary_mid=None,
                         pivot_index=None, current_min_val=None, min_indices=None,
                         extra_vars=None, precision=2):
        self.clear_static_layer()
        self.finalize_running_animations()
        
        anim_group = QParallelAnimationGroup(self)

        # Normalize new_values to dict {arr_name: list_of_vals}
        if isinstance(new_values, dict):
            arr_dict = new_values
        elif isinstance(new_values, list):
            curr_name = list(self.array_rows.keys())[0] if self.array_rows else "a"
            arr_dict = {curr_name: new_values}
        else:
            arr_dict = {}

        # 1. Текстовий коментар до кроку
        if step_description:
            desc_item = self.scene.addText(str(step_description))
            desc_item.setFont(QFont("Consolas", 13, QFont.Bold))
            desc_item.setDefaultTextColor(QColor("#2c3e50"))
            desc_item.setPos(15.0, self.base_y - 75)
            self.static_items.append(desc_item)

        # 2. Метрики — відображаються контекстно
        metrics_parts = []
        if show_capacity_size:
            cap_str = f"Місткість (Capacity): {capacity_metric}" if capacity_metric is not None else ""
            total_elements = sum(len(v) for v in arr_dict.values())
            sz_str = f"Кількість (Size): {size_metric}" if size_metric is not None else f"Кількість (Size): {total_elements}"
            joined_cs = " | ".join(filter(None, [cap_str, sz_str]))
            metrics_parts.append(joined_cs)

        if show_sum_avg:
            # First non-empty array for sum/avg metric
            first_vals = next((v for v in arr_dict.values() if v), [])
            if first_vals:
                curr_sum = sum(first_vals)
                curr_avg = curr_sum / len(first_vals)
                sum_str = f"{curr_sum:.{precision}f}".rstrip('0').rstrip('.') if isinstance(curr_sum, float) else f"{curr_sum}"
                metrics_parts.append(f"Сума: {sum_str} | Сер: {curr_avg:.2f}")
            else:
                metrics_parts.append("Сума: 0 | Сер: 0.00")

        # Conditional accumulation sums
        if extra_vars:
            cond_sums = []
            for k, v in extra_vars.items():
                k_lower = k.lower()
                if "sum" in k_lower and k_lower not in ("sum", "curr_sum", "sum_val"):
                    v_str = f"{v:.{precision}f}".rstrip('0').rstrip('.') if isinstance(v, float) else f"{v}"
                    if "positive" in k_lower or "pos" in k_lower:
                        label = f"Сума додатних ({k})"
                    elif "negative" in k_lower or "neg" in k_lower:
                        label = f"Сума від'ємних ({k})"
                    elif "even" in k_lower:
                        label = f"Сума парних ({k})"
                    elif "odd" in k_lower:
                        label = f"Сума непарних ({k})"
                    else:
                        label = k
                    cond_sums.append(f"{label}: {v_str}")
            if cond_sums:
                metrics_parts.append(" | ".join(cond_sums))

        # Counters / Лічильники
        active_cnts = []
        if extra_vars:
            for k, v in extra_vars.items():
                k_lower = k.lower()
                if any(cw in k_lower for cw in ("count", "counter", "matched", "num_")) and k_lower not in ("count_metric", "capacity", "size"):
                    active_cnts.append(f"{k}: {v}")
        if active_cnts:
            metrics_parts.append(" | ".join(active_cnts))
        elif count_metric is not None and not show_capacity_size:
            metrics_parts.append(f"Кількість за умовою: {count_metric}")

        if current_min_val is not None:
            idxs_str = f" [індекси: {', '.join(map(str, min_indices))}]" if min_indices else ""
            v_str = f"{current_min_val:.{precision}f}".rstrip('0').rstrip('.') if isinstance(current_min_val, float) else f"{current_min_val}"
            metrics_parts.append(f"Мінімум (Min): {v_str}{idxs_str}")

        if current_max_val is not None:
            idxs_str = f" [індекси: {', '.join(map(str, max_indices))}]" if max_indices else ""
            v_str = f"{current_max_val:.{precision}f}".rstrip('0').rstrip('.') if isinstance(current_max_val, float) else f"{current_max_val}"
            metrics_parts.append(f"Максимум (Max): {v_str}{idxs_str}")

        if found_index is not None:
            metrics_parts.append(f"Знайдено індекс: {found_index}")
        elif binary_mid is not None and binary_range is not None:
            metrics_parts.append(f"Діапазон: [{binary_range[0]}...{binary_range[1]}] | mid: {binary_mid}")

        if metrics_parts:
            metrics_str = "   |   ".join(metrics_parts)
            if not self.metrics_item:
                self.metrics_item = self.scene.addText(metrics_str)
                self.metrics_item.setFont(QFont("Consolas", 11, QFont.Bold))
                self.metrics_item.setDefaultTextColor(QColor("#16a085"))
                self.metrics_item.setPos(15.0, self.base_y - 35)
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
                anim = CartoonAnimationHandler.animate_push_back(self.temp_block, temp_pos, duration=self.anim_duration)
                anim.start()
            else:
                self.temp_block.set_text(temp_val)
                self.temp_block.set_bg_color("#9b59b6")
                CartoonAnimationHandler.animate_change(self.temp_block, temp_val, "#8e44ad", duration=self.anim_duration).start()
        else:
            if self.temp_block:
                CartoonAnimationHandler.animate_pop(self.temp_block, self.scene, duration=self.anim_duration).start()
                self.temp_block = None
            if self.temp_label:
                self.scene.removeItem(self.temp_label)
                self.temp_label = None

        # Identify active target array if mentioned in description
        active_target_arr = None
        for aname in arr_dict:
            if f"{aname}[" in step_description or f"{aname}." in step_description or f"({aname})" in step_description:
                active_target_arr = aname
                break

        # Remove rows for arrays no longer present
        existing_names = list(self.array_rows.keys())
        for aname in existing_names:
            if aname not in arr_dict:
                row_info = self.array_rows.pop(aname)
                if row_info['label'].scene() == self.scene:
                    self.scene.removeItem(row_info['label'])
                for bdata in row_info['blocks']:
                    if bdata['item'].scene() == self.scene:
                        self.scene.removeItem(bdata['item'])

        max_idx_set = set(max_indices) if max_indices else set()
        pair_idx_set = set(pair_indices) if pair_indices else set()

        # Render rows for each array
        for row_idx, (arr_name, vals) in enumerate(arr_dict.items()):
            row_y = self.base_y + row_idx * (self.block_height + 45.0)

            if arr_name not in self.array_rows:
                lbl = self.scene.addText(f"{arr_name}:")
                lbl.setFont(QFont("Consolas", 12, QFont.Bold))
                lbl.setDefaultTextColor(QColor("#2c3e50"))
                lbl.setPos(15.0, row_y + 8.0)
                self.array_rows[arr_name] = {'label': lbl, 'blocks': []}
            else:
                lbl = self.array_rows[arr_name]['label']
                lbl.setPos(15.0, row_y + 8.0)
                lbl.setPlainText(f"{arr_name}:")

            blocks_list = self.array_rows[arr_name]['blocks']
            old_count = len(blocks_list)
            new_count = len(vals)
            min_len = min(old_count, new_count)

            is_active_row = (active_target_arr is None or arr_name == active_target_arr)

            for i in range(min_len):
                block_data = blocks_list[i]
                block_item = block_data['item']
                old_val = block_data['value']
                new_val = vals[i]

                # Highlight rules
                if is_active_row and pivot_index is not None and i == pivot_index:
                    target_color = "#e74c3c"  # Pivot (Red)
                elif is_active_row and found_index is not None and i == found_index:
                    target_color = "#2ecc71"  # Match (Green)
                elif is_active_row and binary_mid is not None and i == binary_mid:
                    target_color = "#e67e22"  # Mid (Orange)
                elif is_active_row and binary_range is not None:
                    if binary_range[0] <= i <= binary_range[1]:
                        target_color = "#3498db"  # Range (Blue)
                    else:
                        target_color = "#bdc3c7"  # Out of range (Gray)
                elif is_active_row and search_index is not None and i == search_index:
                    target_color = "#f1c40f"  # Scanning (Yellow)
                elif is_active_row and i in pair_idx_set:
                    target_color = "#e056fd"  # Swap pair (Purple)
                elif is_active_row and i in max_idx_set:
                    target_color = "#f39c12"  # Max (Gold)
                else:
                    target_color = "#33ccff"  # Standard (Cyan)

                if old_val != new_val:
                    block_data['value'] = new_val
                    pulse_anim = CartoonAnimationHandler.animate_change(block_item, new_val, target_color, duration=self.anim_duration)
                    anim_group.addAnimation(pulse_anim)
                else:
                    block_item.set_bg_color(target_color)

            if new_count > old_count:
                for i in range(old_count, new_count):
                    val = vals[i]
                    target_pos = self.get_target_pos(i, row_idx=row_idx)
                    color = "#2ecc71" if (is_active_row and found_index == i) else ("#e056fd" if (is_active_row and i in pair_idx_set) else ("#f39c12" if (is_active_row and i in max_idx_set) else "#99ff99"))
                    new_block = AnimatedArrayBlock(text=val, width=self.block_width, height=self.block_height, bg_color=color)
                    self.scene.addItem(new_block)
                    bounce_anim = CartoonAnimationHandler.animate_push_back(new_block, target_pos, duration=self.anim_duration)
                    anim_group.addAnimation(bounce_anim)
                    blocks_list.append({'item': new_block, 'value': val})

            elif new_count < old_count:
                blocks_to_remove = blocks_list[new_count:]
                self.array_rows[arr_name]['blocks'] = blocks_list[:new_count]
                for block_data in blocks_to_remove:
                    block_item = block_data['item']
                    block_item.set_bg_color("#e74c3c")
                    anim_group.addAnimation(CartoonAnimationHandler.animate_pop(block_item, self.scene, duration=self.anim_duration))

            for i, block_data in enumerate(blocks_list):
                if i < len(vals):
                    block_data['value'] = vals[i]
                    block_data['item'].set_text(vals[i])
                target_pos = self.get_target_pos(i, row_idx=row_idx)
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
    def get_arrays_snapshot(self):
        """Знімок усіх наявних масивів у системі (включаючи 1D, 2D, 3D та багатовимірні) для відображення у UI."""
        res = {}
        for k, v in self.arrays.items():
            if isinstance(v, list):
                if len(v) > 0 and isinstance(v[0], list):
                    if len(v[0]) > 0 and isinstance(v[0][0], list):
                        # 3D Масив: tensor[i][j]
                        for i, layer in enumerate(v):
                            for j, row in enumerate(layer):
                                res[f"{k}[{i}][{j}]"] = list(row)
                    else:
                        # 2D Масив / Матриця: matrix[i]
                        for i, row in enumerate(v):
                            res[f"{k}[{i}]"] = list(row)
                else:
                    res[k] = list(v)
            else:
                res[k] = [v]
        return res


    def make_step(self, desc, pair=None, search_idx=None, found_idx=None, bin_range=None, bin_mid=None, pivot_idx=None):
        extra_vars = {}
        for k, v in self.variables.items():
            k_lower = k.lower()
            if any(kw in k_lower for kw in ("count", "counter", "matched", "num_", "sumpositive", "sumnegative", "sumeven", "sumodd", "sumpos", "sumneg")):
                if k_lower not in ("i", "j", "n", "capacity", "size"):
                    extra_vars[k] = v

        return (
            self.get_arrays_snapshot(),
            str(desc),
            self.has_sum_avg,
            self.condition_count,
            list(self.max_indices) if self.max_indices else None,
            self.current_max_val,
            self.temp_val,
            pair,
            self.has_capacity_size,
            self.current_capacity,
            self.current_size,
            search_idx,
            found_idx,
            bin_range,
            bin_mid,
            pivot_idx,
            self.current_min_val,
            list(self.min_indices) if self.min_indices else None,
            extra_vars,
            getattr(self, "precision", 2)
        )


    @staticmethod
    def split_top_level(s):
        """Розбиття аргументів верхнього рівня за комами з урахуванням вкладених дужок."""
        parts = []
        curr = []
        depth = 0
        for ch in s:
            if ch in '([{<':
                depth += 1
                curr.append(ch)
            elif ch in ')]}>':
                depth -= 1
                curr.append(ch)
            elif ch == ',' and depth == 0:
                parts.append(''.join(curr).strip())
                curr = []
            else:
                curr.append(ch)
        if curr:
            parts.append(''.join(curr).strip())
        return parts

    def resolve_container_target(self, expr_str):
        """
        Універсальне визначення цільового контейнера для сортування, реверсу або обміну.
        Підтримує:
          - 'v' (1D вектор / масив)
          - 'v.begin()', 'v.rbegin()', 'std::begin(v)', 'std::rbegin(v)'
          - 'matrix[0]' (рядок 2D вектора / матриці)
          - 'matrix[1].begin()', 'matrix[1].rbegin()'
        Повертає: (disp_name, list_reference, is_reverse)
        """
        s = expr_str.strip()
        is_rev = bool(re.search(r'\b(?:c?rbegin|c?rend)\b', s))

        # 1. Рядок 2D вектора з ітератором: matrix[0].begin()
        m_row_it = re.match(r'^([a-zA-Z_]\w*)\s*\[([^\]]+)\]\.(?:c?begin|c?end|c?rbegin|c?rend)\s*\(\s*\)$', s)
        if m_row_it:
            aname = m_row_it.group(1)
            r_idx = int(self.eval_expression(m_row_it.group(2)))
            if aname in self.arrays and isinstance(self.arrays[aname], list):
                if 0 <= r_idx < len(self.arrays[aname]):
                    return f"{aname}[{r_idx}]", self.arrays[aname][r_idx], is_rev

        # 2. Рядок 2D вектора: matrix[0]
        m_row = re.match(r'^([a-zA-Z_]\w*)\s*\[([^\]]+)\]$', s)
        if m_row:
            aname = m_row.group(1)
            r_idx = int(self.eval_expression(m_row.group(2)))
            if aname in self.arrays and isinstance(self.arrays[aname], list):
                if 0 <= r_idx < len(self.arrays[aname]):
                    return f"{aname}[{r_idx}]", self.arrays[aname][r_idx], is_rev

        # 3. 1D ітераторний метод: v.begin(), v.rbegin()
        m_it = re.match(r'^([a-zA-Z_]\w*)\.(?:c?begin|c?end|c?rbegin|c?rend)\s*\(\s*\)$', s)
        if m_it:
            cname = m_it.group(1)
            if cname in self.arrays:
                return cname, self.arrays[cname], is_rev

        # 4. std::begin(v), std::rbegin(v)
        m_std_it = re.match(r'^(?:std::)?(?:c?begin|c?end|c?rbegin|c?rend)\s*\(\s*([a-zA-Z_]\w*)\s*\)$', s)
        if m_std_it:
            cname = m_std_it.group(1)
            if cname in self.arrays:
                return cname, self.arrays[cname], is_rev

        # 5. Пряма назва контейнера: 'v'
        if s in self.arrays:
            return s, self.arrays[s], is_rev

        # 6. Fallback до main_array_name
        return s, self.arrays.get(s, self.arrays.get(self.main_array_name, None)), is_rev

    def run_quicksort_visualizer(self, cname, low, high, steps):
        disp_name, arr, _ = self.resolve_container_target(cname)
        if arr is None or not isinstance(arr, list):
            return
        if low >= high or low < 0 or high >= len(arr):
            return

        pivot_idx = high
        pivot_val = arr[pivot_idx]

        cur_temp = self.temp_val if getattr(self, "has_temp_in_code", False) else None

        steps.append((
            self.get_arrays_snapshot(),
            f"QuickSort: Обрано опорний елемент (pivot) = {disp_name}[{pivot_idx}] ({pivot_val}) для діапазону [{low}...{high}]",
            self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, cur_temp, None,
            self.has_capacity_size, self.current_capacity, self.current_size, None, None, [low, high], None, pivot_idx
        ))

        i = low - 1
        for j in range(low, high):
            self.active_pair = [j, pivot_idx]
            steps.append((
                self.get_arrays_snapshot(),
                f"QuickSort: Порівняння {disp_name}[{j}] ({arr[j]}) з pivot ({pivot_val})",
                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, cur_temp, self.active_pair,
                self.has_capacity_size, self.current_capacity, self.current_size, None, None, [low, high], None, pivot_idx
            ))

            if arr[j] <= pivot_val:
                i += 1
                if i != j:
                    self.active_pair = [i, j]
                    old_i, old_j = arr[i], arr[j]
                    arr[i], arr[j] = old_j, old_i
                    steps.append((
                        self.get_arrays_snapshot(),
                        f"QuickSort: {disp_name}[{j}] <= pivot ({pivot_val}). Обмін {disp_name}[{i}] ({old_i}) <-> {disp_name}[{j}] ({old_j})",
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, cur_temp, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, [low, high], None, pivot_idx
                    ))

        pi = i + 1
        if pi != high:
            self.active_pair = [pi, high]
            old_pi, old_h = arr[pi], arr[high]
            arr[pi], arr[high] = old_h, old_pi
            steps.append((
                self.get_arrays_snapshot(),
                f"QuickSort: Встановлення pivot ({pivot_val}) на фінальну позицію [{pi}]",
                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, cur_temp, self.active_pair,
                self.has_capacity_size, self.current_capacity, self.current_size, None, None, [low, high], None, pi
            ))
        else:
            steps.append((
                self.get_arrays_snapshot(),
                f"QuickSort: Pivot ({pivot_val}) вже на правильній позиції [{pi}]",
                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, cur_temp, None,
                self.has_capacity_size, self.current_capacity, self.current_size, None, None, [low, high], None, pi
            ))

        self.temp_val = None
        self.active_pair = None

        self.run_quicksort_visualizer(cname, low, pi - 1, steps)
        self.run_quicksort_visualizer(cname, pi + 1, high, steps)


    """
    Універсальний симулятор та інтерпретатор коду C++20:
    - Стек областей видимості (Scope Stack) для коректної обробки вкладених блоків та змінних
    - Динамічні безпечні ліміти ітерацій відповідно до розмірів масивів
    - Дійсна діагностика синтаксису з виведенням попереджень та помилок обчислення
    - Підтримка всіх видів сортування, бінарного/лінійного пошуків, векторів та стандартних бібліотек C++20
    """
    
    @staticmethod
    def parse_nested_array(init_str):
        """Перетворення списку ініціалізації C++ {{1, 2}, {3, 4}} у вкладений список Python."""
        s = init_str.strip().rstrip(';').strip()
        if not s:
            return []
        py_str = re.sub(r'\{', '[', s)
        py_str = re.sub(r'\}', ']', py_str)
        while py_str.count('[') < py_str.count(']') and py_str.endswith(']'):
            py_str = py_str[:-1].strip()
        try:
            return eval(py_str, {"__builtins__": {}})
        except Exception:
            return []

    @staticmethod
    def create_empty_multidim(dims, fill=0):
        """Створення порожнього багатовимірного масиву за заданими розмірностями."""
        if not dims:
            return fill
        if len(dims) == 1:
            return [fill] * dims[0]
        return [CppUniversalEngine.create_empty_multidim(dims[1:], fill) for _ in range(dims[0])]

    def __init__(self):
        self.scopes = [{}]  # Стек областей видимості
        self.type_aliases = {}
        self.iterators = {}
        self.arrays = {}
        self.main_array_name = "arr"
        self.random_min = 1
        self.random_max = 100
        self.is_real_dist = False
        self.has_sum_avg = False
        self.has_count = False
        self.has_max_search = False
        self.has_capacity_size = False
        self.has_linear_search = False
        self.has_binary_search = False
        self.condition_count = None
        self.max_indices = []
        self.current_max_val = None
        self.temp_val = None
        self.active_pair = None
        self.current_capacity = None
        self.current_size = None
        self.vector_capacities = {}
        self.search_index = None
        self.found_index = None
        self.search_target = None
        self.binary_range = None
        self.binary_mid = None
        self.current_min_val = None
        self.min_indices = []
        self.precision = 2
        self.fixed_format = False
        self.last_eval_error = None


    def pad_multidim(self, vals, dims, default_val=0):
        if not dims:
            return vals
        if len(dims) == 2 and isinstance(vals, list) and len(vals) == 1 and isinstance(vals[0], list) and len(vals[0]) > 0 and isinstance(vals[0][0], list):
            vals = vals[0]
        if len(dims) == 1:
            target_len = dims[0]
            res = list(vals)[:target_len] if isinstance(vals, (list, tuple)) else []
            while len(res) < target_len:
                res.append(default_val)
            return res
        elif len(dims) == 2:
            target_rows, target_cols = dims[0], dims[1]
            res = []
            vals_list = list(vals) if isinstance(vals, (list, tuple)) else []
            for r in range(target_rows):
                row_vals = vals_list[r] if r < len(vals_list) and isinstance(vals_list[r], (list, tuple)) else []
                padded_row = list(row_vals)[:target_cols]
                while len(padded_row) < target_cols:
                    padded_row.append(default_val)
                res.append(padded_row)
            return res
        elif len(dims) == 3:
            target_d1, target_d2, target_d3 = dims[0], dims[1], dims[2]
            res = []
            vals_list = list(vals) if isinstance(vals, (list, tuple)) else []
            for i in range(target_d1):
                layer = vals_list[i] if i < len(vals_list) and isinstance(vals_list[i], (list, tuple)) else []
                layer_list = list(layer) if isinstance(layer, (list, tuple)) else []
                layer_res = []
                for j in range(target_d2):
                    row = layer_list[j] if j < len(layer_list) and isinstance(layer_list[j], (list, tuple)) else []
                    padded_row = list(row)[:target_d3]
                    while len(padded_row) < target_d3:
                        padded_row.append(default_val)
                    layer_res.append(padded_row)
                res.append(layer_res)
            return res
        return vals

    def parse_std_array_type(self, type_str):
        dims = []
        curr = type_str.strip()
        elem_type = "int"
        while True:
            m = re.match(r"^(?:std\s*::\s*)?array\s*<\s*(.+)\s*,\s*([^>]+)\s*>$", curr)
            if not m:
                elem_type = curr.strip()
                break
            inner_type = m.group(1).strip()
            dim_expr = m.group(2).strip()
            dim_val = int(self.eval_expression(dim_expr))
            dims.append(dim_val)
            curr = inner_type
        return dims, elem_type

    def parse_num(self, val):
        if isinstance(val, (set, list, tuple)):
            if len(val) > 0:
                val = list(val)[0]
            else:
                return 0
        if isinstance(val, float):
            return int(val) if val.is_integer() else round(val, 4)
        if isinstance(val, int):
            return val
        if isinstance(val, str):
            val_clean = val.strip().strip({}).strip()
            try:
                f = float(val_clean)
                return int(f) if f.is_integer() else round(f, 4)
            except ValueError:
                pass
        return val

    def eval_int(self, expr_str):
        val = self.parse_num(self.eval_expression(expr_str))
        try:
            return int(val)
        except (ValueError, TypeError):
            return 0

    @property
    def variables(self):
        """Агрегований словник усіх діючих змінних з урахуванням вкладених областей видимості."""
        res = {}
        for scope in self.scopes:
            res.update(scope)
        return res

    def push_scope(self):
        """Створення нової вкладеної області видимості (наприклад, при вході у блок циклу чи умови)."""
        self.scopes.append({})

    def pop_scope(self):
        """Вихід із вкладеної області видимості з очищенням її локальних змінних."""
        if len(self.scopes) > 1:
            self.scopes.pop()

    def get_var(self, name, default=0):
        """Пошук значення змінної, починаючи з найближчої вкладеної області видимості."""
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return default

    def set_var(self, name, val, is_decl=False):
        """Присвоєння значення змінній у відповідній області видимості."""
        if is_decl or not self.scopes:
            self.scopes[-1][name] = val
        else:
            for scope in reversed(self.scopes):
                if name in scope:
                    scope[name] = val
                    return
            self.scopes[-1][name] = val

    def clean_code(self, source):
        prec_m = re.search(r"(?:std\s*::\s*)?setprecision\s*\(\s*(\d+)\s*\)", source)
        if prec_m:
            self.precision = int(prec_m.group(1))
            self.fixed_format = "fixed" in source.lower()
        else:
            self.precision = 2
            self.fixed_format = False

        no_block_comments = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        no_line_comments = re.sub(r"//.*", "", no_block_comments)
        no_cin_stmts = re.sub(r"\b(?:std\s*::\s*)?cin\s*>>\s*[^;]+;", "", no_line_comments)

        # 1. Extract all using type aliases e.g. using Alias = Target;
        self.type_aliases = {}
        for m_u in re.finditer(r"\busing\s+([a-zA-Z_]\w*)\s*=\s*([^;]+);", no_cin_stmts):
            alias = m_u.group(1).strip()
            target = m_u.group(2).strip()
            for k, v in list(self.type_aliases.items()):
                target = re.sub(rf"\b{k}\b", v, target)
            self.type_aliases[alias] = target

        normalized_code = re.sub(r"\busing\s+[a-zA-Z_]\w*\s*=\s*[^;]+;", "", no_cin_stmts)
        normalized_code = re.sub(r"\busing\s+namespace\s+\w+\s*;", "", normalized_code)
        for alias, target in list(self.type_aliases.items()):
            normalized_code = re.sub(rf"\b{alias}\b", target, normalized_code)

        normalized_code = re.sub(r"\bstd\s*::\s*size_t\b", "size_t", normalized_code)

        def repl_comma_decls(m):
            type_str = m.group(1)
            rest = m.group(2)
            if "{" in rest:
                return m.group(0)
            parts = rest.split(",")
            out = []
            for p in parts:
                p = p.strip().rstrip(";")
                if p:
                    if not p.startswith(type_str):
                        p = f"{type_str} {p}"
                    out.append(p)
            return "; ".join(out) + ";"

        def repl_uniform_init(m):
            qual, type_name, var_name, init_val = m.group(1) or "", m.group(2), m.group(3), m.group(4).strip()
            if "{" in init_val or "[" in var_name or "array" in type_name:
                return m.group(0)
            if not init_val:
                init_val = "0.0" if type_name in ("double", "float") else "0"
            return f"{qual}{type_name} {var_name} = {init_val};"

        normalized_code = re.sub(
            r"\b(constexpr\s+|const\s+)?(long\s+long|long|short|char|int|double|float|auto|bool|size_t)\s+([a-zA-Z_]\w*)\s*\{\s*([^}]*)\s*\}\s*;",
            repl_uniform_init,
            normalized_code
        )

        normalized = re.sub(r"\b(long\s+long|long|short|char|int|double|float|auto|bool|size_t)\s+([a-zA-Z_]\w*\s*=[^;]+);?", repl_comma_decls, normalized_code)

        cleaned_lines = []
        for line in normalized.splitlines():
            l = line.strip()
            if l.startswith("#"):
                continue
            cleaned_lines.append(line)
        return " ".join(cleaned_lines)

    def detect_features(self, code):
        code_lower = code.lower()
        self.has_temp_in_code = bool(re.search(r"\btemp\b", code_lower))
        self.is_sorting_context = bool(re.search(r"\b(pass|swapped|indexmin|index_min|sort)\b", code_lower))
        self.has_sum_avg = bool(re.search(r"\b(sum|avg|average|mean|accumulate)\b", code_lower))
        self.has_count = bool(re.search(r"\b(count|counter|matched|count_if)\b", code_lower))
        self.has_max_search = bool(re.search(r"\b(max|maxval|max_val|max_element|maximum)\b", code_lower))
        self.has_capacity_size = bool(re.search(r"\b(capacity|cap|actual_size|vector|push_back|pop_back|reserve|resize|shrink_to_fit)\b", code_lower))
        self.has_binary_search = bool(re.search(r"\b(binary_search|binarysearch|mid|low|high)\b", code_lower))
        self.has_linear_search = bool(re.search(r"\b(find|search|target|key)\b|==\s*target|target\s*==", code_lower)) and not self.has_binary_search
        self.has_quicksort = bool(re.search(r"\b(quick_sort|quicksort|partition|pivot)\b", code_lower))

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

        has_float = "double" in expr or "float" in expr or "." in expr or getattr(self, "is_real_dist", False)

        # C++ цілочисельне ділення / N -> // N лише якщо немає дійсних чисел або явного приведення до float/double
        if not has_float:
            expr = re.sub(r"/\s*(\d+)", r"// \1", expr)

        self.last_eval_error = None

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

        # std::min_element
        min_el_m = re.search(r"(?:std::)?min_element\s*\(([^,]+),\s*([^)]+)\)", expr)
        if min_el_m:
            it1 = self.resolve_iterator_expr(min_el_m.group(1))
            cname = it1.container_name if isinstance(it1, CppIterator) else self.main_array_name
            if cname in self.arrays and self.arrays[cname]:
                arr = self.arrays[cname]
                m_val = min(arr)
                self.current_min_val = m_val
                self.min_indices = [idx for idx, x in enumerate(arr) if x == m_val]
                expr = expr.replace(min_el_m.group(0), str(m_val))

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

        # 3D Array access tensor[i][j][k]
        def repl_3d_access(m):
            aname, r1, r2, r3 = m.group(1), m.group(2), m.group(3), m.group(4)
            if aname in self.arrays and isinstance(self.arrays[aname], list):
                try:
                    i1, i2, i3 = int(self.eval_expression(r1)), int(self.eval_expression(r2)), int(self.eval_expression(r3))
                    return str(self.arrays[aname][i1][i2][i3])
                except Exception:
                    pass
            return m.group(0)
        expr = re.sub(r"\b(\w+)\s*\[([^\]]+)\]\s*\[([^\]]+)\]\s*\[([^\]]+)\]", repl_3d_access, expr)

        # 2D Array access matrix[i][j]
        def repl_2d_access(m):
            aname, r1, r2 = m.group(1), m.group(2), m.group(3)
            if aname in self.arrays and isinstance(self.arrays[aname], list):
                try:
                    i1, i2 = int(self.eval_expression(r1)), int(self.eval_expression(r2))
                    return str(self.arrays[aname][i1][i2])
                except Exception:
                    pass
            return m.group(0)
        expr = re.sub(r"\b(\w+)\s*\[([^\]]+)\]\s*\[([^\]]+)\]", repl_2d_access, expr)

        # 1D Array access arr[i]
        def repl_array_access(m):
            aname = m.group(1)
            raw_i = m.group(2) or m.group(3)
            if aname in self.arrays and isinstance(self.arrays[aname], list):
                try:
                    eval_idx = int(self.eval_expression(raw_i))
                    arr_ref = self.arrays[aname]
                    if 0 <= eval_idx < len(arr_ref):
                        return str(arr_ref[eval_idx])
                except Exception:
                    pass
            return m.group(0)
        expr = re.sub(r"\b(\w+)\s*(?:\[([^\]]+)\]|\.at\s*\(([^)]+)\))", repl_array_access, expr)

        for name, arr in self.arrays.items():
            if isinstance(arr, list) and len(arr) > 0 and isinstance(arr[0], list):
                expr = re.sub(rf"\b(?:std\s*::\s*)?(?:s)?size\s*\(\s*{name}\s*\[[^\]]+\]\s*\)", str(len(arr[0])), expr)
                expr = re.sub(rf"\b(?:std\s*::\s*)?(?:s)?size\s*\(\s*{name}\s*\)", str(len(arr)), expr)
            elif isinstance(arr, list):
                expr = re.sub(rf"\b(?:std\s*::\s*)?(?:s)?size\s*\(\s*{name}\s*\)", str(len(arr)), expr)
            if arr:
                expr = re.sub(rf"\b{name}\.front\s*\(\s*\)", str(arr[0]), expr)
                expr = re.sub(rf"\b{name}\.back\s*\(\s*\)", str(arr[-1]), expr)
            expr = re.sub(rf"\b{name}\.size\s*\(\s*\)", str(len(arr)), expr)
            expr = re.sub(rf"\b{name}\.empty\s*\(\s*\)", str(len(arr) == 0), expr)
            expr = re.sub(rf"\b{name}\.capacity\s*\(\s*\)", str(self.vector_capacities.get(name, self.current_capacity or len(arr))), expr)

        expr = re.sub(r"\(\s*(?:double|float|int)\s*\)", "", expr)
        expr = re.sub(r"static_cast\s*<\s*(?:double|float)\s*>\s*\(([^)]+)\)", r"float(\1)", expr)
        expr = re.sub(r"static_cast\s*<\s*int\s*>\s*\(([^)]+)\)", r"int(\1)", expr)

        expr = re.sub(r"\brand\s*\(\s*\)", str(random.randint(0, 32767)), expr)
        expr = re.sub(r"\b\w*dist\w*\s*\(\s*\w*\s*\)", f"__random_val()", expr, flags=re.IGNORECASE)

        env = {
            "__random_val": lambda: round(random.uniform(self.random_min, self.random_max), 2) if getattr(self, "is_real_dist", False) else random.randint(int(self.random_min), int(self.random_max)),
            "size_t": int,
            "float": float,
            "double": float,
            "int": int,
            "nullptr": 0,
            "NULL": 0
        }
        env.update(self.variables)

        if self.main_array_name in self.arrays:
            env.setdefault("N", len(self.arrays[self.main_array_name]))
            env.setdefault("n", len(self.arrays[self.main_array_name]))

        try:
            res = eval(expr, {"__builtins__": {}}, env)
            return self.parse_num(res)
        except Exception as e:
            self.last_eval_error = f"Обчислення '{expr_str}': {e}"
            if "dist" in expr or "gen" in expr:
                return round(random.uniform(self.random_min, self.random_max), 2) if getattr(self, "is_real_dist", False) else random.randint(int(self.random_min), int(self.random_max))
            return 0

    def run(self, code_text):
        self.scopes = [{}]
        self.iterators.clear()
        self.arrays.clear()
        self.main_array_name = "arr"
        self.random_min, self.random_max = 1, 100
        self.is_real_dist = False
        self.condition_count = None
        self.max_indices = []
        self.current_max_val = None
        self.temp_val = None
        self.active_pair = None
        self.current_capacity = None
        self.current_size = None
        self.vector_capacities.clear()
        self.search_index = None
        self.found_index = None
        self.search_target = None
        self.binary_range = None
        self.binary_mid = None
        self.current_min_val = None
        self.min_indices = []
        self.precision = 2
        self.fixed_format = False
        self.last_eval_error = None
        steps = []

        code = self.clean_code(code_text)
        self.detect_features(code)

        real_dist_match = re.search(r"uniform_real_distribution\s*(?:<[^>]+>)?\s*\w+\s*\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)", code)
        if real_dist_match:
            self.is_real_dist = True
            self.random_min = float(real_dist_match.group(1))
            self.random_max = float(real_dist_match.group(2))
        else:
            dist_match = re.search(r"uniform_int_distribution\s*(?:<[^>]+>)?\s*\w+\s*\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)", code)
            if dist_match:
                self.random_min = int(dist_match.group(1))
                self.random_max = int(dist_match.group(2))

        main_match = re.search(r"int\s+main\s*\([^)]*\)\s*\{(.*)\}", code, re.DOTALL)
        body = main_match.group(1) if main_match else code

        # Автоматичне створення тестового масиву, якщо немає явного оголошення
        has_decl = bool(re.search(r"(?:int|auto|vector|array)\s+\w+\s*\[|\bvector\s*<|\barray\s*<|\bto_array\b", body))
        if not has_decl and ("a[" in body or "arr[" in body or "binary" in body or "mid" in body or "quick" in body or "pivot" in body):
            var_guess = "a" if "a[" in body else "arr"
            self.main_array_name = var_guess
            self.arrays[var_guess] = [5, 12, 18, 25, 33, 47, 56, 68, 79, 91]
            self.set_var("N", len(self.arrays[var_guess]), is_decl=True)
            self.set_var("n", len(self.arrays[var_guess]), is_decl=True)
            self.current_capacity = len(self.arrays[var_guess])
            self.current_size = len(self.arrays[var_guess])
            steps.append((self.get_arrays_snapshot(), f"Вхідний відсортований масив: {var_guess} = [5, 12, 18, 25, 33, 47, 56, 68, 79, 91]", False, None, None, None, None, None, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))

        self.execute_block(body, steps)
        if self.current_size is not None and self.main_array_name in self.arrays and len(self.arrays[self.main_array_name]) > self.current_size:
            self.arrays[self.main_array_name] = self.arrays[self.main_array_name][:self.current_size]
            steps.append((self.get_arrays_snapshot(),
                f"Результат обробки / відбору за умовою: відібрано {self.current_size} елементів = {self.arrays[self.main_array_name]}",
                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
            ))

        return steps

    def clean_condition(self, cond_str):
        c_clean = str(cond_str)
        c_clean = re.sub(r'!\s*\(\s*(?:std\s*::\s*)?cin\s*>>\s*[^)]+\)', ' False ', c_clean)
        c_clean = re.sub(r'!\s*(?:std\s*::\s*)?cin\s*>>\s*\w+', ' False ', c_clean)
        c_clean = re.sub(r'(?:std\s*::\s*)?cin\s*>>\s*[^&|()]+', ' True ', c_clean)
        c_clean = re.sub(r"!=", "__NOT_EQUAL__", c_clean)
        c_clean = re.sub(r"&&", " and ", c_clean)
        c_clean = re.sub(r"\|\|", " or ", c_clean)
        c_clean = re.sub(r"!", " not ", c_clean)
        c_clean = re.sub(r"__NOT_EQUAL__", " != ", c_clean)

        # 3D Array access tensor[i][j][k]
        def repl_3d_cond(m):
            aname, r1, r2, r3 = m.group(1), m.group(2), m.group(3), m.group(4)
            if aname in self.arrays and isinstance(self.arrays[aname], list):
                try:
                    i1, i2, i3 = int(self.eval_expression(r1)), int(self.eval_expression(r2)), int(self.eval_expression(r3))
                    return str(self.arrays[aname][i1][i2][i3])
                except Exception:
                    pass
            return m.group(0)
        c_clean = re.sub(r"\b(\w+)\s*\[([^\]]+)\]\s*\[([^\]]+)\]\s*\[([^\]]+)\]", repl_3d_cond, c_clean)

        # 2D Array access matrix[i][j]
        def repl_2d_cond(m):
            aname, r1, r2 = m.group(1), m.group(2), m.group(3)
            if aname in self.arrays and isinstance(self.arrays[aname], list):
                try:
                    i1, i2 = int(self.eval_expression(r1)), int(self.eval_expression(r2))
                    return str(self.arrays[aname][i1][i2])
                except Exception:
                    pass
            return m.group(0)
        c_clean = re.sub(r"\b(\w+)\s*\[([^\]]+)\]\s*\[([^\]]+)\]", repl_2d_cond, c_clean)

        def repl_arr(m):
            aname = m.group(1)
            raw_i = m.group(2) or m.group(3)
            if aname in self.arrays and isinstance(self.arrays[aname], list):
                try:
                    eval_idx = int(self.eval_expression(raw_i))
                    arr_ref = self.arrays[aname]
                    if 0 <= eval_idx < len(arr_ref):
                        return str(arr_ref[eval_idx])
                except Exception:
                    pass
            return m.group(0)
        c_clean = re.sub(r"\b(\w+)\s*(?:\[([^\]]+)\]|\.at\s*\(([^)]+)\))", repl_arr, c_clean)

        for k, v in self.variables.items():
            c_clean = re.sub(rf"\b{k}\b", str(v), c_clean)

        for name, arr in self.arrays.items():
            if isinstance(arr, list) and len(arr) > 0 and isinstance(arr[0], list):
                c_clean = re.sub(rf"\b(?:std\s*::\s*)?(?:s)?size\s*\(\s*{name}\s*\[[^\]]+\]\s*\)", str(len(arr[0])), c_clean)
                c_clean = re.sub(rf"\b(?:std\s*::\s*)?(?:s)?size\s*\(\s*{name}\s*\)", str(len(arr)), c_clean)
            elif isinstance(arr, list):
                c_clean = re.sub(rf"\b(?:std\s*::\s*)?(?:s)?size\s*\(\s*{name}\s*\)", str(len(arr)), c_clean)
            c_clean = re.sub(rf"\b{name}\.size\s*\(\s*\)", str(len(arr)), c_clean)
            c_clean = re.sub(rf"\b{name}\.empty\s*\(\s*\)", str(len(arr) == 0), c_clean)
            c_clean = re.sub(rf"\b{name}\.capacity\s*\(\s*\)", str(self.vector_capacities.get(name, self.current_capacity or len(arr))), c_clean)

        return c_clean

    def run_while_loop(self, cond_str, body_str, steps):
        arr_len = len(self.arrays.get(self.main_array_name, [10]))
        max_safety = max(1500, arr_len * arr_len * 10)
        count = 0
        while count < max_safety:
            c_clean = self.clean_condition(cond_str)
            try:
                if not eval(c_clean):
                    break
            except Exception:
                break

            if self.found_index is not None and "break" in body_str:
                break

            self.push_scope()
            self.execute_block(body_str, steps)
            self.pop_scope()
            count += 1

    def execute_block(self, block_str, steps):
        def extract_sub_body(s_str, start_idx):
            idx_cur = start_idx
            len_s = len(s_str)
            while idx_cur < len_s and s_str[idx_cur].isspace():
                idx_cur += 1
            if idx_cur < len_s and s_str[idx_cur] == '{':
                depth = 1
                j = idx_cur + 1
                while j < len_s and depth > 0:
                    if s_str[j] == '{': depth += 1
                    elif s_str[j] == '}': depth -= 1
                    j += 1
                return s_str[idx_cur + 1 : j - 1], j
            else:
                rem = s_str[idx_cur:].lstrip()
                if rem.startswith("for") or rem.startswith("while") or rem.startswith("if"):
                    p_start = s_str.find("(", idx_cur)
                    if p_start != -1:
                        depth_p = 1
                        kp = p_start + 1
                        while kp < len_s and depth_p > 0:
                            if s_str[kp] == '(': depth_p += 1
                            elif s_str[kp] == ')': depth_p -= 1
                            kp += 1
                        sub_b, next_k = extract_sub_body(s_str, kp)
                        return s_str[idx_cur:next_k], next_k
                j = s_str.find(';', idx_cur)
                return (s_str[idx_cur : j + 1] if j != -1 else ""), (j + 1 if j != -1 else len_s)

        i = 0
        n = len(block_str)

        while i < n:
            while i < n and block_str[i].isspace():
                i += 1
            if i >= n:
                break

            if block_str[i:].startswith("while"):
                m_while = re.match(r"while\s*\(", block_str[i:])
                if m_while:
                    start_cond = i + m_while.end()
                    depth_p = 1
                    k_p = start_cond
                    while k_p < n and depth_p > 0:
                        if block_str[k_p] == '(': depth_p += 1
                        elif block_str[k_p] == ')': depth_p -= 1
                        k_p += 1
                    condition_str = block_str[start_cond:k_p-1]
                    while_body, i = extract_sub_body(block_str, k_p)
                    self.run_while_loop(condition_str, while_body, steps)
                    continue

            if block_str[i:].startswith("if"):
                m_if = re.match(r"if\s*\(", block_str[i:])
                if m_if:
                    start_cond = i + m_if.end()
                    depth_p = 1
                    k_p = start_cond
                    while k_p < n and depth_p > 0:
                        if block_str[k_p] == '(': depth_p += 1
                        elif block_str[k_p] == ')': depth_p -= 1
                        k_p += 1
                    condition_str = block_str[start_cond:k_p-1]
                    if_body, i = extract_sub_body(block_str, k_p)
                    self.run_if_condition(condition_str, if_body, steps)
                    continue

            if block_str[i:].startswith("for"):
                m_for = re.match(r"for\s*\(", block_str[i:])
                if m_for:
                    start_cond = i + m_for.end()
                    depth_p = 1
                    k_p = start_cond
                    while k_p < n and depth_p > 0:
                        if block_str[k_p] == '(': depth_p += 1
                        elif block_str[k_p] == ')': depth_p -= 1
                        k_p += 1
                    header = block_str[start_cond:k_p-1]
                    body_stmt, i = extract_sub_body(block_str, k_p)
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
        cond_clean = self.clean_condition(cond_expr)

        def repl_arr(m):
            aname = m.group(1)
            raw_i = m.group(2) or m.group(3)
            if aname in self.arrays:
                try:
                    eval_idx = int(self.eval_expression(raw_i))
                    arr_ref = self.arrays[aname]
                    if 0 <= eval_idx < len(arr_ref):
                        return str(arr_ref[eval_idx])
                except Exception:
                    pass
            return m.group(0)

        cond_clean = re.sub(r"\b(\w+)\s*(?:\[([^\]]+)\]|\.at\s*\(([^)]+)\))", repl_arr, cond_clean)
        for k, v in self.variables.items():
            cond_clean = re.sub(rf"\b{k}\b", str(v), cond_clean)

        try:
            cond_result = bool(eval(cond_clean))
        except Exception:
            cond_result = False

        cond_arr_match = re.search(r"\b(\w+)\s*(?:\[|\.at\()", cond_expr)
        target_arr_name = cond_arr_match.group(1) if (cond_arr_match and cond_arr_match.group(1) in self.arrays) else self.main_array_name
        curr_arr = list(self.arrays.get(target_arr_name, []))
        
        is_binary_match = bool(re.search(r"mid", cond_expr.lower()) and "==" in cond_expr)
        is_binary_less_or_more = bool(re.search(r"mid", cond_expr.lower()) and ("<" in cond_expr or ">" in cond_expr))
        is_search_cond = bool(re.search(r"==\s*target|target\s*==|==\s*key|key\s*==", cond_expr) and ("[" in cond_expr or ".at" in cond_expr)) and not is_binary_match
        is_min_cond = bool(re.search(r"<\s*\w*(?:\[(?:index)?min|\.at\((?:index)?min|\bmin\b)|\bmin\b\s*>", cond_expr.lower()))
        is_max_cond = bool(re.search(r">\s*\w*(?:\[(?:index)?max|\.at\((?:index)?max|\bmax\b)|\bmax\b\s*<", cond_expr.lower()))
        is_sort_cond = bool(re.search(r"\[[^\]]+\]\s*[><]\s*[^[]*\[[^\]]+\]|\.at\([^)]+\)\s*[><]\s*[^.]*\.at\([^)]+\)", cond_expr)) and not is_min_cond and not is_max_cond
        is_filter_cond = bool(re.search(r">\s*0|<\s*0|%\s*2\s*==|!=\s*0|count\s*<|size\s*<|capacity", cond_expr.lower())) and not is_min_cond and not is_max_cond and not is_sort_cond

        curr_i = None
        idx_search_match = re.search(r"\[\s*(\w+)\s*\]|\.at\s*\(\s*(\w+)\s*\)", cond_expr)
        if idx_search_match:
            raw_v = idx_search_match.group(1) or idx_search_match.group(2)
            curr_i = self.get_var(raw_v, None) if not raw_v.isdigit() else int(raw_v)

        if is_search_cond and curr_i is not None and 0 <= curr_i < len(curr_arr):
            self.search_index = curr_i

        if is_sort_cond:
            raw_matches = re.findall(r"\[([^\]]+)\]|\.at\s*\(([^)]+)\)", cond_expr)
            idxs = []
            for m in raw_matches:
                s_idx = m[0] if m[0] else m[1]
                if s_idx.strip():
                    try:
                        idxs.append(int(self.eval_expression(s_idx)))
                    except Exception:
                        pass
            if len(idxs) >= 2:
                self.active_pair = [idxs[0], idxs[1]]

        if cond_result:
            if is_binary_match:
                mid_val = int(self.get_var("mid", 0))
                self.found_index = mid_val
                steps.append((self.get_arrays_snapshot(), 
                    f"Двійковий пошук: ЕЛЕМЕНТ ЗНАЙДЕНО! {self.main_array_name}[mid={mid_val}] == target ({curr_arr[mid_val]})", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, self.found_index, self.binary_range, self.binary_mid
                ))
            elif is_binary_less_or_more:
                mid_val = int(self.get_var("mid", 0))
                steps.append((self.get_arrays_snapshot(), 
                    f"Двійковий пошук: ({cond_expr}) -> ТАК. Звуження меж пошуку.", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, self.binary_range, self.binary_mid
                ))
            elif is_search_cond:
                self.found_index = curr_i
                steps.append((self.get_arrays_snapshot(), 
                    f"Лінійний пошук: ЕЛЕМЕНТ ЗНАЙДЕНО у {target_arr_name}[{curr_i}] = {curr_arr[curr_i]}! (break)", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, self.found_index, None, None
                ))
            elif is_sort_cond:
                steps.append((self.get_arrays_snapshot(), 
                    f"Сортування: умова ({cond_expr}) -> ТАК. Потрібен обмін елементів!", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                ))
            
            self.push_scope()
            self.execute_block(body_stmt, steps)
            self.pop_scope()

            if "low" in self.variables and "high" in self.variables:
                self.binary_range = [self.get_var("low"), self.get_var("high")]

            if is_min_cond:
                for k in self.variables:
                    if "min" in k.lower() and "max" not in k.lower() and "mid" not in k.lower():
                        val = self.get_var(k)
                        if "index" in k.lower() or "idx" in k.lower():
                            if 0 <= val < len(curr_arr):
                                self.current_min_val = curr_arr[val]
                                self.min_indices = [i for i, x in enumerate(curr_arr) if x == self.current_min_val]
                        else:
                            self.current_min_val = val
                            self.min_indices = [i for i, x in enumerate(curr_arr) if x == self.current_min_val]
                        break
                steps.append(self.make_step(f"Знайдено новий мінімум: {self.current_min_val} [індекс(и): {', '.join(map(str, self.min_indices))}]"))
            elif is_max_cond:
                for k in self.variables:
                    if "max" in k.lower():
                        val = self.get_var(k)
                        if "index" in k.lower() or "idx" in k.lower():
                            if 0 <= val < len(curr_arr):
                                self.current_max_val = curr_arr[val]
                                self.max_indices = [i for i, x in enumerate(curr_arr) if x == self.current_max_val]
                        else:
                            self.current_max_val = val
                            self.max_indices = [i for i, x in enumerate(curr_arr) if x == self.current_max_val]
                        break
                steps.append(self.make_step(f"Знайдено новий максимум: {self.current_max_val} [індекс(и): {', '.join(map(str, self.max_indices))}]"))
            elif is_filter_cond:
                cnt_val = self.get_var("count", self.get_var("size", self.condition_count))
                self.current_size = cnt_val
                steps.append((self.get_arrays_snapshot(), 
                    f"Відбір: Умова ({cond_expr}) -> ПІДХОДИТЬ. Елемент відібрано! Кількість: {cnt_val}", 
                    self.has_sum_avg, cnt_val, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                ))
        else:
            if is_binary_match:
                mid_val = int(self.get_var("mid", 0))
                steps.append((self.get_arrays_snapshot(), 
                    f"Двійковий пошук: {self.main_array_name}[mid={mid_val}] ({curr_arr[mid_val]}) != target. Продовжуємо поділ навпіл.", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, self.binary_range, self.binary_mid
                ))
            elif is_search_cond:
                val_now = curr_arr[curr_i] if (curr_i is not None and 0 <= curr_i < len(curr_arr)) else ""
                steps.append((self.get_arrays_snapshot(), 
                    f"Лінійний пошук: перевірка зліва направо [{curr_i}] = {val_now} (не збігається)", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, self.search_index, None, None, None
                ))
            elif is_sort_cond:
                steps.append((self.get_arrays_snapshot(), 
                    f"Сортування: умова ({cond_expr}) -> НІ. Елементи вже впорядковані.", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                ))
                self.active_pair = None
            elif is_min_cond:
                steps.append(self.make_step(f"Порівняння: ({cond_expr}) -> Ні (поточний мінімум: {self.current_min_val})"))
            elif is_max_cond:
                steps.append(self.make_step(f"Порівняння: ({cond_expr}) -> Ні (поточний максимум: {self.current_max_val})"))
            elif is_filter_cond:
                cnt_val = self.get_var("count", self.get_var("size", self.condition_count))
                steps.append((self.get_arrays_snapshot(), 
                    f"Відбір: Умова ({cond_expr}) -> НЕ підходить (пропущено).", 
                    self.has_sum_avg, cnt_val, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                ))

    def run_for_loop(self, header, body, steps):
        if ":" in header and ";" not in header:
            var_part, cont_part = [p.strip() for p in header.split(":", 1)]
            var_name = var_part.replace("&", "").split()[-1].strip()
            cont_expr = cont_part.strip()
            arr_data = None
            if cont_expr in self.arrays:
                arr_data = self.arrays[cont_expr]
            else:
                m_idx = re.match(r"^([a-zA-Z_]\w*)\s*\[([^\]]+)\]$", cont_expr)
                if m_idx:
                    aname = m_idx.group(1)
                    idx_val = int(self.eval_expression(m_idx.group(2)))
                    if aname in self.arrays and 0 <= idx_val < len(self.arrays[aname]):
                        arr_data = self.arrays[aname][idx_val]
            
            if arr_data is not None and isinstance(arr_data, (list, tuple)):
                for idx in range(len(arr_data)):
                    self.push_scope()
                    self.set_var(var_name, arr_data[idx], is_decl=True)
                    self.execute_block(body, steps)
                    if "&" in var_part and self.get_var(var_name) != arr_data[idx]:
                        old = arr_data[idx]
                        arr_data[idx] = self.get_var(var_name)
                        steps.append((self.get_arrays_snapshot(), f"{cont_expr}[{idx}] = {arr_data[idx]} (було {old})", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
                    self.pop_scope()
            return

        parts = header.split(';')
        if len(parts) != 3:
            return

        init_part, cond_part, inc_part = [p.strip() for p in parts]
        
        is_iter_loop = False
        loop_iter_name = ""

        self.push_scope()

        if ("iterator" in init_part or "auto" in init_part) and "=" in init_part:
            lhs, rhs = init_part.split('=', 1)
            loop_iter_name = lhs.split()[-1].strip()
            it_obj = self.resolve_iterator_expr(rhs)
            if it_obj:
                self.iterators[loop_iter_name] = it_obj
                is_iter_loop = True
            else:
                iter_var = loop_iter_name
                self.set_var(iter_var, int(self.eval_expression(rhs)), is_decl=True)
        elif "=" in init_part:
            lhs, rhs = init_part.split('=', 1)
            iter_var = lhs.split()[-1].strip()
            self.set_var(iter_var, int(self.eval_expression(rhs)), is_decl=True)

        arr_len = len(self.arrays.get(self.main_array_name, [10]))
        max_safety_iterations = max(1500, arr_len * arr_len * 10)  # Гнучкий безпечний ліміт
        it_count = 0

        while it_count < max_safety_iterations:
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
                c_expr = self.clean_condition(cond_part)
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
                    self.set_var(vname, self.get_var(vname, 0) + 1)
                elif "--" in inc_part:
                    vname = inc_part.replace("--", "").strip()
                    self.set_var(vname, self.get_var(vname, 0) - 1)
                elif "+=" in inc_part:
                    vname, step_str = inc_part.split("+=", 1)
                    vname = vname.strip()
                    self.set_var(vname, self.get_var(vname, 0) + int(self.eval_expression(step_str)))

            it_count += 1

        self.pop_scope()

    def execute_statement(self, stmt, steps):
        s = " ".join(stmt.split()).strip()
        if not s or s.startswith("cout") or s.startswith("return") or s.startswith("std::cout"):
            return
        if re.search(r"\b(?:std\s*::\s*)?cin\s*>>", s):
            return

        # --- 3D Присвоєння: a[i][j][k] = val ---
        m_3d_assign = re.match(r"^(\w+)\s*\[([^\]]+)\]\s*\[([^\]]+)\]\s*\[([^\]]+)\]\s*=\s*(.+)$", s)
        if m_3d_assign:
            target_name = m_3d_assign.group(1)
            idx1 = int(self.eval_expression(m_3d_assign.group(2)))
            idx2 = int(self.eval_expression(m_3d_assign.group(3)))
            idx3 = int(self.eval_expression(m_3d_assign.group(4)))
            val = self.parse_num(self.eval_expression(m_3d_assign.group(5)))
            if target_name in self.arrays and isinstance(self.arrays[target_name], list):
                try:
                    old = self.arrays[target_name][idx1][idx2][idx3]
                    self.arrays[target_name][idx1][idx2][idx3] = val
                    steps.append((self.get_arrays_snapshot(),
                        f"{target_name}[{idx1}][{idx2}][{idx3}] = {val} (було {old})",
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                except IndexError:
                    pass
            return

        # --- 2D Присвоєння: a[i][j] = val ---
        m_2d_assign = re.match(r"^(\w+)\s*\[([^\]]+)\]\s*\[([^\]]+)\]\s*=\s*(.+)$", s)
        if m_2d_assign:
            target_name = m_2d_assign.group(1)
            idx1 = int(self.eval_expression(m_2d_assign.group(2)))
            idx2 = int(self.eval_expression(m_2d_assign.group(3)))
            val = self.parse_num(self.eval_expression(m_2d_assign.group(4)))
            if target_name in self.arrays and isinstance(self.arrays[target_name], list):
                try:
                    old = self.arrays[target_name][idx1][idx2]
                    self.arrays[target_name][idx1][idx2] = val
                    steps.append((self.get_arrays_snapshot(),
                        f"{target_name}[{idx1}][{idx2}] = {val} (було {old})",
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                except IndexError:
                    pass
            return

        # --- 2D/3D Оголошення багатовимірних масивів ---
        # Nested std::array declaration e.g. std::array<std::array<double, 4>, 3> a{};
        if "array" in s and ("<" in s):
            m_std_arr = re.search(r"^((?:std\s*::\s*)?array\s*<.+>)\s+([a-zA-Z_]\w*)\s*(?:=\s*|\{\s*)(.*)$", s)
            if m_std_arr:
                type_part = m_std_arr.group(1)
                name = m_std_arr.group(2)
                rest_init = m_std_arr.group(3)
                dims, elem_type = self.parse_std_array_type(type_part)
                if dims and len(dims) >= 2:
                    self.main_array_name = name
                    def_val = 0.0 if elem_type in ("double", "float") else 0
                    init_vals = []
                    brace_m = re.search(r"(\{.*\})", rest_init)
                    if brace_m:
                        init_vals = self.parse_nested_array(brace_m.group(1))
                    init_vals = self.pad_multidim(init_vals, dims, def_val)
                    self.arrays[name] = init_vals
                    shape_str = "".join(f"[{d}]" for d in dims)
                    steps.append((self.get_arrays_snapshot(),
                        f"Оголошено багатовимірний std::array: {name}{shape_str}",
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                    return

        # Multidimensional C-array declaration e.g. double carrots[3][4] {}; or double carrots[][4] { ... };
        m_multidim_decl = re.search(r"(?:int|auto|double|float|long|short|char|bool|size_t)\s+([a-zA-Z_]\w*)\s*((?:\[[^\]]*\])+)", s)
        if m_multidim_decl:
            name = m_multidim_decl.group(1)
            elem_type = m_multidim_decl.group(0).split()[0]
            raw_dims = re.findall(r"\[([^\]]*)\]", m_multidim_decl.group(2))
            brace_m = re.search(r"=\s*(\{.*\})", s) or re.search(r"(\{.*\});?$", s)
            init_str = brace_m.group(1) if brace_m else ""
            
            dims = []
            for d in raw_dims:
                d_str = d.strip()
                if d_str:
                    dims.append(int(self.eval_expression(d_str)))
                else:
                    if init_str:
                        top_lists = re.findall(r"\{[^{}]*\}", init_str)
                        dims.append(len(top_lists))
                    else:
                        dims.append(1)

            if dims and len(dims) >= 2:
                self.main_array_name = name
                def_val = 0.0 if "double" in elem_type or "float" in elem_type else 0
                init_vals = []
                if brace_m:
                    init_vals = self.parse_nested_array(brace_m.group(1))
                init_vals = self.pad_multidim(init_vals, dims, def_val)
                self.arrays[name] = init_vals
                shape_str = "".join(f"[{d}]" for d in dims)
                steps.append((self.get_arrays_snapshot(),
                    f"Оголошено багатовимірний масив: {name}{shape_str}",
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                ))
                return
        if not s or s.startswith("cout") or s.startswith("return") or s.startswith("std::cout"):
            return
        if re.search(r"\b(?:std\s*::\s*)?cin\s*>>", s):
            return

        for cname in list(self.arrays.keys()):
            s = re.sub(rf"\b{cname}\.front\s*\(\s*\)", f"{cname}[0]", s)
            if self.arrays[cname]:
                s = re.sub(rf"\b{cname}\.back\s*\(\s*\)", f"{cname}[{len(self.arrays[cname])-1}]", s)

        # 0. std::to_array
        to_array_m = re.search(r"(?:(?:auto|(?:std\s*::\s*)?array\s*(?:<[^>]+>)?)\s+)?([a-zA-Z_]\w*)\s*=\s*(?:std\s*::\s*)?to_array\s*(?:<[^>]+>)?\s*\(\s*\{([^}]*)\}\s*\)", s)
        if to_array_m:
            name = to_array_m.group(1).strip()
            raw_vals = to_array_m.group(2).strip()
            self.main_array_name = name

            init_vals = []
            if raw_vals:
                init_vals = [self.parse_num(self.eval_expression(x)) for x in raw_vals.split(',') if x.strip()]

            sz = len(init_vals)
            self.arrays[name] = list(init_vals)
            self.set_var("N", sz, is_decl=True)
            self.set_var("n", sz, is_decl=True)
            self.current_capacity = sz
            self.current_size = sz
            steps.append((self.get_arrays_snapshot(), 
                f"Оголошено std::array (через std::to_array): {name}[{sz}] = {{{', '.join(map(str, init_vals))}}}", 
                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, 
                self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
            ))
            return

        # Standalone inc/dec or compound ops (j--, j++, ++j, --j, j -= 1, j += 1)
        inc_dec_m = re.match(r"^(\+\+|--)?([a-zA-Z_]\w*)(\+\+|--)?$", s)
        if inc_dec_m and inc_dec_m.group(2) not in self.arrays:
            vname = inc_dec_m.group(2)
            op = inc_dec_m.group(1) or inc_dec_m.group(3)
            curr = self.get_var(vname, 0)
            new_val = curr + 1 if op == "++" else curr - 1
            self.set_var(vname, new_val)
            if any(kw in vname.lower() for kw in ("count", "counter", "matched", "num_")):
                self.condition_count = new_val
                steps.append(self.make_step(f"Лічильник ({vname}): {vname} = {new_val} ({'+1' if op == '++' else '-1'})"))
            return

        plus_minus_m = re.match(r"^([a-zA-Z_]\w*)\s*(\+=|-=)\s*(.+)$", s)
        if plus_minus_m and plus_minus_m.group(1) not in self.arrays and plus_minus_m.group(1) not in ("count", "counter", "matched", "size", "actual_size", "sum"):
            vname = plus_minus_m.group(1)
            op = plus_minus_m.group(2)
            val_add = self.eval_expression(plus_minus_m.group(3))
            curr = self.get_var(vname, 0)
            if op == "+=":
                self.set_var(vname, curr + val_add)
            elif op == "-=":
                self.set_var(vname, curr - val_add)
            return

        # Змінні: int temp = a[j], long long sumPositive{}, int i = 0, low, high, mid, target
        var_assign_m = re.match(r"^(?:(?:constexpr|const|long\s+long|long|short|char|int|double|float|auto|bool|size_t)\s+)+([a-zA-Z_]\w*)\s*(?:=\s*|\{\s*)([^{}]*)\s*\}?;?$", s) or re.match(r"^([a-zA-Z_]\w*)\s*=\s*([^;{}]+);?$", s)
        if var_assign_m and "array" not in s and "vector" not in s and "[" not in s.split("=")[0]:
            vname = var_assign_m.group(1)
            rhs = var_assign_m.group(2).rstrip(';').strip()
            if rhs in self.arrays:
                self.arrays[vname] = list(self.arrays[rhs])
                self.main_array_name = vname
                self.current_size = len(self.arrays[vname])
                steps.append((self.get_arrays_snapshot(), f"Створено масив / копію: {vname} = {rhs}", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
                return
            val_eval = self.parse_num(self.eval_expression(rhs))
            is_decl_flag = bool(re.search(r"\b(?:int|auto|double|float|bool|size_t)\b", s.split("=")[0]))
            self.set_var(vname, val_eval, is_decl=is_decl_flag)

            curr_arr = list(self.arrays.get(self.main_array_name, []))

            if "temp" in vname.lower():
                self.temp_val = self.parse_num(val_eval)
                idx_m = re.search(r"\[([^\]]+)\]", rhs) or re.search(r"\.at\s*\(([^)]+)\)", rhs)
                if idx_m:
                    first_i = int(self.eval_expression(idx_m.group(1)))
                    self.active_pair = [first_i, min(first_i + 1, len(curr_arr) - 1)]
                    steps.append((self.get_arrays_snapshot(), 
                        f"Збереження в буфер: temp = {self.main_array_name}[{first_i}] ({self.temp_val})", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                else:
                    steps.append((self.get_arrays_snapshot(), 
                        f"Збереження в буфер: temp = {self.temp_val}", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                return

            if vname.lower() == "mid":
                mid_idx = int(val_eval)
                self.binary_mid = mid_idx
                low_val = int(self.get_var("low", 0))
                high_val = int(self.get_var("high", len(curr_arr) - 1))
                self.binary_range = [low_val, high_val]
                val_str = curr_arr[mid_idx] if 0 <= mid_idx < len(curr_arr) else '?'
                steps.append((self.get_arrays_snapshot(), 
                    f"Двійковий пошук: обчислення mid = {mid_idx} (значення {val_str})", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, self.binary_range, self.binary_mid
                ))
                return

            if vname.lower() in ("low", "high"):
                low_val = self.get_var("low", 0)
                high_val = self.get_var("high", len(curr_arr) - 1)
                self.binary_range = [low_val, high_val]
                steps.append((self.get_arrays_snapshot(), 
                    f"Двійковий пошук: оновлено межу {vname} = {val_eval}. Новий діапазон: [{low_val}...{high_val}]", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, self.binary_range, None
                ))
                return

            if "target" in vname.lower() or "key" in vname.lower():
                self.search_target = int(val_eval)
                if "key" in vname.lower():
                    cur_temp = self.parse_num(val_eval) if getattr(self, "has_temp_in_code", False) else None
                    self.temp_val = cur_temp
                    msg_title = f"Ключ сортування вставками: {vname} = {val_eval}"
                else:
                    msg_title = f"Шукане значення для пошуку: {vname} = {val_eval}"
                steps.append((self.get_arrays_snapshot(), 
                    msg_title, 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                ))
                return

            if "found" in vname.lower():
                val_i = int(val_eval)
                if val_i >= 0:
                    self.found_index = val_i
                steps.append((self.get_arrays_snapshot(), 
                    f"Прапорчик пошуку: {vname} = {val_i}", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, self.found_index, None, None
                ))
                return

            return  # Return here for all other scalar variables!

        # 1. std::binary_search
        bin_search_call = re.match(r"(?:bool\s+\w+\s*=)?\s*(?:std::)?binary_search\s*\(([^,]+),\s*([^,]+),\s*([^)]+)\)", s)
        if bin_search_call:
            it1 = self.resolve_iterator_expr(bin_search_call.group(1))
            cname = it1.container_name if isinstance(it1, CppIterator) else self.main_array_name
            target_val = self.parse_num(self.eval_expression(bin_search_call.group(3)))

            if cname in self.arrays:
                arr = self.arrays[cname]
                steps.append((
                    list(arr), 
                    f"Запуск std::binary_search({cname}, target={target_val})", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                ))

                low, high = 0, len(arr) - 1
                found = False
                while low <= high:
                    mid = low + (high - low) // 2
                    self.binary_range = [low, high]
                    self.binary_mid = mid

                    steps.append((
                        list(arr), 
                        f"std::binary_search: діапазон [{low}...{high}], mid={mid} (значення {arr[mid]})", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, self.binary_range, self.binary_mid
                    ))

                    if arr[mid] == target_val:
                        found = True
                        steps.append((
                            list(arr), 
                            f"std::binary_search: ЕЛЕМЕНТ ЗНАЙДЕНО на позиції [{mid}] == {target_val}!", 
                            self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                            self.has_capacity_size, self.current_capacity, self.current_size, None, mid, self.binary_range, self.binary_mid
                        ))
                        break
                    elif arr[mid] < target_val:
                        low = mid + 1
                    else:
                        high = mid - 1

                if not found:
                    steps.append((
                        list(arr), 
                        f"std::binary_search: елемент {target_val} НЕ знайдено у масиві", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                return

        # 2. std::find
        find_call = re.match(r"(?:auto\s+(\w+)\s*=)?\s*(?:std::)?find\s*\(([^,]+),\s*([^,]+),\s*([^)]+)\)", s)
        if find_call:
            it1 = self.resolve_iterator_expr(find_call.group(2))
            cname = it1.container_name if isinstance(it1, CppIterator) else self.main_array_name
            target_val = self.parse_num(self.eval_expression(find_call.group(4)))

            if cname in self.arrays:
                arr = self.arrays[cname]
                steps.append((
                    list(arr), 
                    f"Запуск std::find({cname}): пошук значення {target_val} зліва направо", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                ))

                found_pos = None
                for scan_i in range(len(arr)):
                    if arr[scan_i] == target_val:
                        found_pos = scan_i
                        steps.append((
                            list(arr), 
                            f"std::find: ЕЛЕМЕНТ ЗНАЙДЕНО на позиції [{scan_i}] == {target_val}!", 
                            self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                            self.has_capacity_size, self.current_capacity, self.current_size, None, scan_i, None, None
                        ))
                        break
                    else:
                        steps.append((
                            list(arr), 
                            f"std::find: сканування [{scan_i}] = {arr[scan_i]} (!= {target_val})", 
                            self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                            self.has_capacity_size, self.current_capacity, self.current_size, scan_i, None, None, None
                        ))

                if found_pos is None:
                    steps.append((
                        list(arr), 
                        f"std::find: елемент {target_val} НЕ знайдено", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                return

                # 3.1. quick_sort / quickSort / quicksort
        qs_call = re.match(r"^(?:(?:void|int)\s+)?(?:std\s*::\s*)?(?:quick_sort|quickSort|quicksort)\s*\((.*)\);?$", s)
        if qs_call:
            args = self.split_top_level(qs_call.group(1))
            if args:
                target_name, arr, _ = self.resolve_container_target(args[0])
                if arr is not None and isinstance(arr, list):
                    low_idx = 0
                    high_idx = len(arr) - 1
                    if len(args) >= 3:
                        try:
                            low_idx = int(self.eval_expression(args[1]))
                            high_idx = int(self.eval_expression(args[2]))
                        except Exception:
                            pass

                    steps.append((
                        self.get_arrays_snapshot(),
                        f"Запуск Quick Sort (Швидке сортування) для {target_name}[{low_idx}...{high_idx}]",
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None, None
                    ))

                    self.run_quicksort_visualizer(target_name, low_idx, high_idx, steps)

                    steps.append((
                        self.get_arrays_snapshot(),
                        f"Quick Sort ({target_name}): масив повністю відсортовано!",
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None, None
                    ))
                    return

        # 3. std::sort / std::ranges::sort / std::stable_sort (1D & 2D вектори/масиви)
        sort_call = re.match(r"^(?:(?:void|auto)\s+)?(?:std\s*::\s*)?(?:ranges\s*::\s*)?(?:stable_)?sort\s*\((.*)\);?$", s)
        if sort_call:
            args = self.split_top_level(sort_call.group(1))
            if args:
                cname, arr, is_rev = self.resolve_container_target(args[0])
                descending = is_rev or any("greater" in a for a in args) or any("rbegin" in a for a in args)

                if arr is not None and isinstance(arr, list):
                    is_2d_rows = len(arr) > 0 and isinstance(arr[0], list)

                    steps.append((
                        self.get_arrays_snapshot(),
                        f"Запуск std::sort({cname}) {'(за спаданням)' if descending else '(за зростанням)'}",
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))

                    n_len = len(arr)
                    cur_temp = self.temp_val if getattr(self, "has_temp_in_code", False) else None
                    for step_i in range(n_len):
                        for step_j in range(0, n_len - step_i - 1):
                            self.active_pair = [step_j, step_j + 1]
                            need_swap = (arr[step_j] < arr[step_j + 1]) if descending else (arr[step_j] > arr[step_j + 1])
                            if need_swap:
                                old_j, old_j1 = arr[step_j], arr[step_j + 1]
                                arr[step_j], arr[step_j + 1] = old_j1, old_j
                                val_s0 = f"{cname}[{step_j}] ({old_j1})" if not is_2d_rows else f"рядок {cname}[{step_j}]"
                                val_s1 = f"{cname}[{step_j+1}] ({old_j})" if not is_2d_rows else f"рядок {cname}[{step_j+1}]"
                                steps.append((
                                    self.get_arrays_snapshot(),
                                    f"std::sort: обмін {val_s0} <-> {val_s1}",
                                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val,
                                    cur_temp, self.active_pair,
                                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                                ))
                    self.temp_val = None
                    self.active_pair = None
                    steps.append((
                        self.get_arrays_snapshot(),
                        f"std::sort({cname}): масив повністю відсортовано!",
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                    return

        # 4. std::swap (вектори, елементи .at() та зрізи матриць)
        swap_util = re.match(r"^(?:std\s*::\s*)?swap\s*\((.*)\);?$", s)
        if swap_util:
            args = self.split_top_level(swap_util.group(1))
            if len(args) == 2:
                arg1, arg2 = args[0], args[1]

                # 4.1. 2D swap: matrix[0][i], matrix[0][j]
                m2_1 = re.match(r"^([a-zA-Z_]\w*)\s*\[([^\]]+)\]\s*\[([^\]]+)\]$", arg1)
                m2_2 = re.match(r"^([a-zA-Z_]\w*)\s*\[([^\]]+)\]\s*\[([^\]]+)\]$", arg2)
                if m2_1 and m2_2 and m2_1.group(1) == m2_2.group(1):
                    aname = m2_1.group(1)
                    r1 = int(self.eval_expression(m2_1.group(2)))
                    r2 = int(self.eval_expression(m2_2.group(2)))
                    c1 = int(self.eval_expression(m2_1.group(3)))
                    c2 = int(self.eval_expression(m2_2.group(3)))
                    if aname in self.arrays and r1 == r2 and isinstance(self.arrays[aname], list):
                        if 0 <= r1 < len(self.arrays[aname]):
                            row = self.arrays[aname][r1]
                            if 0 <= c1 < len(row) and 0 <= c2 < len(row):
                                self.active_pair = [c1, c2]
                                old1, old2 = row[c1], row[c2]
                                row[c1], row[c2] = old2, old1
                                steps.append((
                                    self.get_arrays_snapshot(),
                                    f"std::swap: успішно поміняно місцями {aname}[{r1}][{c1}] ({old2}) <-> {aname}[{r1}][{c2}] ({old1})",
                                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, self.active_pair,
                                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                                ))
                                self.active_pair = None
                                return

                # 4.2. 1D swap: v[i], v[j] або v.at(i), v.at(j)
                m1_1 = re.match(r"^([a-zA-Z_]\w*)\s*(?:\[([^\]]+)\]|\.at\s*\(([^)]+)\))$", arg1)
                m1_2 = re.match(r"^([a-zA-Z_]\w*)\s*(?:\[([^\]]+)\]|\.at\s*\(([^)]+)\))$", arg2)
                if m1_1 and m1_2 and m1_1.group(1) == m1_2.group(1):
                    cname = m1_1.group(1)
                    idx1 = int(self.eval_expression(m1_1.group(2) or m1_1.group(3)))
                    idx2 = int(self.eval_expression(m1_2.group(2) or m1_2.group(3)))

                    if cname in self.arrays:
                        arr = self.arrays[cname]
                        if 0 <= idx1 < len(arr) and 0 <= idx2 < len(arr):
                            self.active_pair = [idx1, idx2]
                            old1, old2 = arr[idx1], arr[idx2]
                            arr[idx1], arr[idx2] = old2, old1

                            if getattr(self, "has_temp_in_code", False):
                                self.temp_val = old1
                                steps.append((
                                    self.get_arrays_snapshot(),
                                    f"std::swap: збережено {cname}[{idx1}] у temp = {self.temp_val}",
                                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                                ))
                                steps.append((
                                    self.get_arrays_snapshot(),
                                    f"std::swap: успішно поміняно місцями [{idx1}] та [{idx2}]",
                                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, self.active_pair,
                                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                                ))
                                self.temp_val = None
                            else:
                                steps.append((
                                    self.get_arrays_snapshot(),
                                    f"std::swap: успішно поміняно місцями {cname}[{idx1}] ({old2}) <-> {cname}[{idx2}] ({old1})",
                                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, self.active_pair,
                                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                                ))
                            self.active_pair = None
                            return

        # 5. Відбір result[count++] = a[i];
        filter_push = re.search(r"(\w+)\s*(?:\.at\s*\(\s*(\w+)\s*\+\+\s*\)|\[\s*(\w+)\s*\+\+\s*\])\s*=\s*(.+)", s)
        if filter_push:
            res_arr_name = filter_push.group(1)
            cnt_var_name = filter_push.group(2) or filter_push.group(3)
            val_to_add = self.parse_num(self.eval_expression(filter_push.group(4)))

            curr_cnt = self.get_var(cnt_var_name, 0)
            if res_arr_name not in self.arrays or not self.arrays[res_arr_name]:
                self.arrays[res_arr_name] = [val_to_add]
            else:
                if curr_cnt < len(self.arrays[res_arr_name]):
                    self.arrays[res_arr_name][curr_cnt] = val_to_add
                else:
                    self.arrays[res_arr_name].append(val_to_add)
            
            self.set_var(cnt_var_name, curr_cnt + 1)
            self.current_size = curr_cnt + 1

            trimmed = list(self.arrays[res_arr_name][:self.current_size])

            steps.append((self.get_arrays_snapshot(), 
                f"Відбір елемента: {res_arr_name}[{curr_cnt}] = {val_to_add} (фактична кількість: {self.current_size})", 
                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
            ))
            return

        # 6. std::reverse / std::ranges::reverse (вектори, масиви та рядки матриць)
        reverse_call = re.match(r"^(?:(?:void|auto)\s+)?(?:std\s*::\s*)?(?:ranges\s*::\s*)?reverse\s*\((.*)\);?$", s)
        if reverse_call:
            args = self.split_top_level(reverse_call.group(1))
            if args:
                cname, arr, _ = self.resolve_container_target(args[0])
                if arr is not None and isinstance(arr, list):
                    left = 0
                    right = len(arr) - 1
                    if len(args) >= 2:
                        it1 = self.resolve_iterator_expr(args[0])
                        it2 = self.resolve_iterator_expr(args[1])
                        left = it1.index if isinstance(it1, CppIterator) else 0
                        right = (it2.index - 1) if isinstance(it2, CppIterator) else (len(arr) - 1)

                    steps.append((
                        self.get_arrays_snapshot(),
                        f"Запуск reverse({cname}): симетричний розворот від [{left}] до [{right}]",
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))

                    while left < right:
                        self.active_pair = [left, right]
                        old_l, old_r = arr[left], arr[right]
                        arr[left], arr[right] = old_r, old_l
                        if getattr(self, "has_temp_in_code", False):
                            self.temp_val = old_l
                            steps.append((
                                self.get_arrays_snapshot(),
                                f"Реверс: пара [{left}] <-> [{right}]. Збережено temp = {self.temp_val}",
                                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                                self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                            ))
                            steps.append((
                                self.get_arrays_snapshot(),
                                f"Реверс: {cname}[{right}] = temp ({self.temp_val}). Пара успішно обміняна!",
                                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                                self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                            ))
                        else:
                            steps.append((
                                self.get_arrays_snapshot(),
                                f"Реверс: успішно обміняно {cname}[{left}] ({old_r}) <-> {cname}[{right}] ({old_l})",
                                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, self.active_pair,
                                self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                            ))
                        left += 1
                        right -= 1

                    self.temp_val = None
                    self.active_pair = None
                    steps.append((
                        self.get_arrays_snapshot(),
                        f"Реверс масиву {cname} повністю виконано!",
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                    return

        # 7. std::advance
        advance_m = re.search(r"(?:std::)?advance\s*\(\s*(\w+)\s*,\s*([^)]+)\)", s)
        if advance_m:
            it_name = advance_m.group(1)
            dist = int(self.eval_expression(advance_m.group(2)))
            if it_name in self.iterators:
                it_obj = self.iterators[it_name]
                it_obj.index += (-dist if it_obj.is_reverse else dist)
            return

        # 8. Ітератори
        if ("iterator" in s or "auto" in s) and "=" in s and not ("vector<" in s and "::" not in s):
            lhs, rhs = s.split("=", 1)
            it_name = lhs.split()[-1].strip()
            it_obj = self.resolve_iterator_expr(rhs)
            if it_obj:
                self.iterators[it_name] = it_obj
                return

        # 9. *it = val
        deref_assign = re.match(r"^\*\s*(\w+)\s*=\s*(.+)$", s)
        if deref_assign:
            it_name = deref_assign.group(1)
            val = self.parse_num(self.eval_expression(deref_assign.group(2)))
            if it_name in self.iterators:
                it_obj = self.iterators[it_name]
                target_name = it_obj.container_name
                if target_name in self.arrays:
                    arr = self.arrays[target_name]
                    idx = it_obj.index
                    if 0 <= idx < len(arr):
                        old = arr[idx]
                        arr[idx] = val
                        steps.append((list(arr), f"{target_name}[{idx}] = {val} (було {old})", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
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

        # 10. std::array<type, size>
        array_lib_m = re.search(r"(?:std\s*::\s*)?array\s*<\s*[\w:]+\s*,\s*([^>]+)>\s*(\w+)", s)
        if array_lib_m:
            raw_sz = array_lib_m.group(1).strip()
            name = array_lib_m.group(2).strip()
            self.main_array_name = name

            sz = min(max(int(self.eval_expression(raw_sz)), 0), 25)
            init_vals = []
            brace_m = re.search(r"\{([^}]*)\}", s)
            if brace_m and brace_m.group(1).strip():
                init_vals = [self.parse_num(self.eval_expression(x)) for x in brace_m.group(1).split(',') if x.strip()]

            self.arrays[name] = [0] * sz
            for idx, val in enumerate(init_vals[:sz]):
                self.arrays[name][idx] = val

            self.set_var("N", sz, is_decl=True)
            self.set_var("n", sz, is_decl=True)
            self.current_capacity = sz
            self.current_size = len(init_vals) if init_vals else sz
            steps.append((self.get_arrays_snapshot(), f"Оголошено std::array: {name}[{sz}]", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
            return

        # 11. delete[] arr;
        delete_m = re.search(r"delete\s*\[\s*\]\s*(\w+)", s)
        if delete_m:
            target_name = delete_m.group(1)
            if target_name in self.arrays:
                self.arrays[target_name].clear()
                self.current_size = 0
                steps.append((self.get_arrays_snapshot(), f"{target_name}.clear()", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
            return

        # 12. new int[N];
        new_m = re.search(r"(?:(?:int|double|float|auto)\s*\*\s*)?(\w+)\s*=\s*new\s+\w+\s*\[([^\]]*)\]", s)
        if new_m:
            name = new_m.group(1)
            raw_sz = new_m.group(2).strip()
            self.main_array_name = name

            init_vals = []
            brace_m = re.search(r"\{([^}]*)\}", s)
            if brace_m and brace_m.group(1).strip():
                init_vals = [self.parse_num(self.eval_expression(x)) for x in brace_m.group(1).split(',') if x.strip()]

            sz = int(self.eval_expression(raw_sz)) if raw_sz else (len(init_vals) if init_vals else 5)
            sz = min(max(sz, 0), 25)
            self.arrays[name] = [0] * sz
            for idx, val in enumerate(init_vals[:sz]):
                self.arrays[name][idx] = val

            self.set_var("N", sz, is_decl=True)
            self.set_var("n", sz, is_decl=True)
            self.current_capacity = sz
            self.current_size = len(init_vals) if init_vals else sz
            steps.append((self.get_arrays_snapshot(), f"Оголошено динам. масив: {name}[{sz}] (місткість: {sz})", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
            return

        # 13. arr = temp;
        ptr_assign = re.match(r"^(\w+)\s*=\s*(\w+)$", s)
        if ptr_assign:
            lhs = ptr_assign.group(1)
            rhs = ptr_assign.group(2)
            if rhs in self.arrays:
                self.arrays[lhs] = list(self.arrays[rhs])
                self.main_array_name = lhs
                steps.append((self.get_arrays_snapshot(), f"Оголошено масив: {lhs}[{len(self.arrays[lhs])}]", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
                return
            elif rhs in self.iterators:
                self.iterators[lhs] = self.iterators[rhs].clone()
                return
            elif rhs in self.variables:
                self.set_var(lhs, self.get_var(rhs))
                return

        # 14. std::vector (1D, 2D, 3D, дійсні та цілі числа)
        m_vec = re.match(r"^(?:(?:const|constexpr)\s+)?(?:std\s*::\s*)?vector\s*<(.+)>\s*([a-zA-Z_]\w*)\s*(.*)$", s.rstrip(";"))
        if m_vec and not s.startswith("return"):
            inner_type = m_vec.group(1).strip()
            name = m_vec.group(2).strip()
            rest = m_vec.group(3).strip()

            depth = inner_type.count("vector") + 1
            elem_type = "double" if ("double" in inner_type or "float" in inner_type) else "int"
            def_val = 0.0 if elem_type == "double" else 0

            self.main_array_name = name
            arr_val = []

            if "{" in rest:
                brace_m = re.search(r"(\{.*\})", rest)
                if brace_m:
                    init_str = brace_m.group(1).strip()
                    if depth >= 2:
                        arr_val = self.parse_nested_array(init_str)
                    else:
                        raw = init_str.strip("{}").strip()
                        arr_val = [self.parse_num(self.eval_expression(x)) for x in raw.split(",") if x.strip()][:25]
            elif "(" in rest:
                paren_m = re.search(r"\((.*)\)", rest)
                if paren_m:
                    content = paren_m.group(1).strip()
                    if depth == 1:
                        args = [a.strip() for a in content.split(",")]
                        sz = min(max(int(self.eval_expression(args[0])), 0), 25)
                        val = self.parse_num(self.eval_expression(args[1])) if len(args) > 1 else def_val
                        arr_val = [val] * sz
                    elif depth == 2:
                        parts = content.split(",", 1)
                        rows = min(max(int(self.eval_expression(parts[0].strip())), 0), 25)
                        inner_paren = re.search(r"\((.*)\)", parts[1])
                        cols = 0
                        val = def_val
                        if inner_paren:
                            inner_args = [a.strip() for a in inner_paren.group(1).split(",")]
                            cols = min(max(int(self.eval_expression(inner_args[0])), 0), 25)
                            val = self.parse_num(self.eval_expression(inner_args[1])) if len(inner_args) > 1 else def_val
                        arr_val = [[val] * cols for _ in range(rows)]
            else:
                arr_val = []

            self.arrays[name] = arr_val
            sz = len(arr_val)
            self.set_var("N", sz, is_decl=True)
            self.set_var("n", sz, is_decl=True)
            cap = sz
            self.vector_capacities[name] = cap
            self.current_capacity = cap
            self.current_size = sz

            if depth == 1:
                init_desc = f" = {{{', '.join(map(str, arr_val))}}}" if arr_val else " (порожній)"
                desc = f"Оголошено std::vector: {name}[{sz}]{init_desc}"
            else:
                shape_str = f"[{len(arr_val)}][{len(arr_val[0]) if arr_val else 0}]"
                desc = f"Оголошено багатовимірний std::vector: {name}{shape_str}"

            steps.append((
                self.get_arrays_snapshot(),
                desc,
                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                True, self.current_capacity, self.current_size, None, None, None, None
            ))
            return

        # Vector direct assignment v = {1, 2, 3};
        vec_assign_list = re.match(r"^([a-zA-Z_]\w*)\s*=\s*\{([^}]*)\};?$", s)
        if vec_assign_list and vec_assign_list.group(1) in self.arrays:
            target_name = vec_assign_list.group(1)
            raw_vals = vec_assign_list.group(2).strip()
            new_vals = [self.parse_num(self.eval_expression(x)) for x in raw_vals.split(',') if x.strip()]
            self.arrays[target_name] = new_vals
            self.current_size = len(new_vals)
            self.current_capacity = max(self.vector_capacities.get(target_name, 0), len(new_vals))
            self.vector_capacities[target_name] = self.current_capacity
            steps.append((
                self.get_arrays_snapshot(),
                f"{target_name} = {{{', '.join(map(str, new_vals))}}}",
                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                True, self.current_capacity, self.current_size, None, None, None, None
            ))
            return

        # 15. Класичний масив C: int arr[N] = {...}
        arr_decl = re.search(r"(?:int|auto|double|float)\s+(\w+)\s*\[([^\]]*)\]", s)
        if arr_decl and "=" not in s[:arr_decl.start(2)-1]:
            name = arr_decl.group(1)
            raw_sz = arr_decl.group(2).strip()
            self.main_array_name = name

            init_vals = []
            brace_m = re.search(r"\{([^}]*)\}", s)
            if brace_m and brace_m.group(1).strip():
                init_vals = [self.parse_num(self.eval_expression(x)) for x in brace_m.group(1).split(',') if x.strip()]

            sz = int(self.eval_expression(raw_sz)) if raw_sz else (len(init_vals) if init_vals else 5)
            sz = min(max(sz, 0), 25)
            self.arrays[name] = [0] * sz
            for idx, val in enumerate(init_vals[:sz]):
                self.arrays[name][idx] = val

            self.set_var("N", sz, is_decl=True)
            self.set_var("n", sz, is_decl=True)
            self.current_capacity = sz
            self.current_size = len(init_vals) if init_vals else sz
            steps.append((self.get_arrays_snapshot(), f"Оголошено масив: {name}[{sz}]", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
            return

        # 16. .at()
        at_assign_m = re.match(r"^(\w+)\.at\s*\(\s*([^)]+)\s*\)\s*=\s*(.+)$", s)
        if at_assign_m:
            target_name = at_assign_m.group(1)
            raw_idx = at_assign_m.group(2)
            raw_val = at_assign_m.group(3)
            idx = self.eval_int(raw_idx)
            val = self.parse_num(self.eval_expression(raw_val))

            if target_name in self.arrays:
                arr = self.arrays[target_name]
                if 0 <= idx < len(arr):
                    old = arr[idx]
                    arr[idx] = val
                    if "temp" in raw_val.lower():
                        steps.append((list(arr), f"Сортування / Зсув: {target_name}.at({idx}) = temp ({val}) (завершено)", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
                        self.temp_val = None
                    else:
                        steps.append((list(arr), f"{target_name}.at({idx}) = {val} (було {old})", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
                else:
                    steps.append((list(arr), f"std::out_of_range: {target_name}.at({idx}) поза межами", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
            return

        s = re.sub(r"\*\s*\(\s*(\w+)\s*\+\s*([^)]+)\)\s*=", r"\1[\2] =", s)
        s = re.sub(r"(\w+)\.front\s*\(\s*\)\s*=", r"\1[0] =", s)

        # 17. Лічильники count++
        for cnt_alias in ("count", "counter", "matched", "size", "actual_size"):
            if re.match(rf"^(\+\+{cnt_alias}|{cnt_alias}\+\+)$", s):
                self.set_var(cnt_alias, self.get_var(cnt_alias, 0) + 1)
                self.condition_count = self.get_var(cnt_alias)
                self.current_size = self.get_var(cnt_alias)
                curr_arr = list(self.arrays.get(self.main_array_name, []))
                steps.append((self.get_arrays_snapshot(), f"Підрахунок: {cnt_alias} = {self.current_size} (+1)", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
                return

        # 18. Сума +=
        plus_eq_m = re.match(r"^(\w+)\s*(\+=|-=)\s*(.+)$", s)
        if plus_eq_m:
            vname = plus_eq_m.group(1).strip()
            op = plus_eq_m.group(2)
            val_add = self.eval_expression(plus_eq_m.group(3))
            curr = self.get_var(vname, 0)
            new_val = self.parse_num(curr + val_add if op == "+=" else curr - val_add)
            self.set_var(vname, new_val)
            v_lower = vname.lower()
            if "sum" in v_lower:
                if "positive" in v_lower or "pos" in v_lower:
                    msg = f"Умовне накопичення (додатні): {vname} = {new_val} (+{val_add})"
                elif "negative" in v_lower or "neg" in v_lower:
                    msg = f"Умовне накопичення (від'ємні): {vname} = {new_val} ({val_add})"
                elif "even" in v_lower:
                    msg = f"Умовне накопичення (парні): {vname} = {new_val} (+{val_add})"
                elif "odd" in v_lower:
                    msg = f"Умовне накопичення (непарні): {vname} = {new_val} (+{val_add})"
                else:
                    msg = f"Накопичення суми: {vname} = {new_val} ({'+' if val_add >= 0 else ''}{val_add})"
                steps.append(self.make_step(msg))
            elif "count" in v_lower or "size" in v_lower:
                self.condition_count = new_val
                self.current_size = new_val
                steps.append(self.make_step(f"Лічильник / Кількість: {vname} = {new_val}"))
            return

        target_name = self.main_array_name
        for aname in self.arrays:
            if s.startswith(aname + ".") or s.startswith(aname + "["):
                target_name = aname
                break

        # 19. Змінні: low, high, mid, target, temp, maxVal
        if not target_name or target_name not in self.arrays:
            if "=" in s:
                lhs, rhs = s.split("=", 1)
                is_decl_flag = bool(re.search(r"\b(?:int|auto|double|float|bool)\b", lhs))
                vname = lhs.replace("*", "").split()[-1].strip()

                # Двійковий пошук: розрахунок mid
                if vname.lower() == "mid":
                    val_eval = self.parse_num(self.eval_expression(rhs))
                    self.set_var(vname, val_eval, is_decl=is_decl_flag)
                    self.binary_mid = val_eval
                    curr_arr = list(self.arrays.get(self.main_array_name, []))
                    low_val = self.get_var("low", 0)
                    high_val = self.get_var("high", len(curr_arr) - 1)
                    self.binary_range = [low_val, high_val]
                    steps.append((self.get_arrays_snapshot(), 
                        f"Двійковий пошук: обчислення mid = {val_eval} (значення {curr_arr[val_eval] if 0 <= val_eval < len(curr_arr) else '?'})", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, self.binary_range, self.binary_mid
                    ))
                    return

                # Двійковий пошук: зміна low або high
                if vname.lower() in ("low", "high"):
                    val_eval = self.parse_num(self.eval_expression(rhs))
                    self.set_var(vname, val_eval, is_decl=is_decl_flag)
                    curr_arr = list(self.arrays.get(self.main_array_name, []))
                    low_val = self.get_var("low", 0)
                    high_val = self.get_var("high", len(curr_arr) - 1)
                    self.binary_range = [low_val, high_val]
                    steps.append((self.get_arrays_snapshot(), 
                        f"Двійковий пошук: оновлено межу {vname} = {val_eval}. Новий діапазон: [{low_val}...{high_val}]", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, self.binary_range, None
                    ))
                    return

                if "target" in vname.lower() or "key" in vname.lower():
                    val_eval = self.parse_num(self.eval_expression(rhs))
                    self.set_var(vname, val_eval, is_decl=is_decl_flag)
                    self.search_target = val_eval
                    curr_arr = list(self.arrays.get(self.main_array_name, []))
                    steps.append((self.get_arrays_snapshot(), 
                        f"Шукане значення для пошуку: {vname} = {val_eval}", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                    return

                if "cap" in vname.lower():
                    val_eval = self.parse_num(self.eval_expression(rhs))
                    self.set_var(vname, val_eval, is_decl=is_decl_flag)
                    self.current_capacity = val_eval
                    curr_arr = list(self.arrays.get(self.main_array_name, []))
                    steps.append((self.get_arrays_snapshot(), 
                        f"Визначено місткість (Capacity): {vname} = {val_eval}", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                    return

                if "temp" in vname.lower():
                    val_eval = self.eval_expression(rhs)
                    self.set_var(vname, val_eval, is_decl=is_decl_flag)
                    self.temp_val = self.parse_num(val_eval)
                    curr_arr = list(self.arrays.get(self.main_array_name, []))
                    
                    is_shift_start = bool(re.search(r"\[\s*0\s*\]|\.at\s*\(\s*0\s*\)", rhs))
                    if is_shift_start:
                        steps.append((self.get_arrays_snapshot(), 
                            f"Циклічний зсув ліворуч: збереження {self.main_array_name}[0] у temp = {self.temp_val}", 
                            self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, [0],
                            self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                        ))
                        return

                    idx_match = re.search(r"\[([^\]]+)\]", rhs) or re.search(r"\.at\s*\(([^)]+)\)", rhs)
                    if idx_match:
                        first_i = int(self.eval_expression(idx_match.group(1)))
                        sym_i = len(curr_arr) - 1 - first_i
                        if 0 <= first_i < len(curr_arr) and 0 <= sym_i < len(curr_arr) and first_i != sym_i:
                            self.active_pair = [min(first_i, sym_i), max(first_i, sym_i)]
                            steps.append((self.get_arrays_snapshot(), 
                                f"Реверс: Симетрична пара [{self.active_pair[0]}] та [{self.active_pair[1]}]. Збережено temp = {self.temp_val}", 
                                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                                self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                            ))
                            return

                    steps.append((self.get_arrays_snapshot(), 
                        f"Обмін / Сортування: збережено temp = {self.temp_val}", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                    return

                it_try = self.resolve_iterator_expr(rhs)
                if it_try:
                    self.iterators[vname] = it_try
                else:
                    val_eval = self.eval_expression(rhs)
                    self.set_var(vname, val_eval, is_decl=is_decl_flag)
                    curr_arr = list(self.arrays.get(self.main_array_name, []))

                    if "max" in vname.lower():
                        self.current_max_val = self.parse_num(val_eval)
                        self.max_indices = [idx for idx, x in enumerate(curr_arr) if x == self.current_max_val]
                        steps.append((self.get_arrays_snapshot(), 
                            f"Ініціалізація максимуму: {vname} = {self.current_max_val}", 
                            self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                            self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                        ))
                    elif "min" in vname.lower():
                        self.current_min_val = self.parse_num(val_eval)
                        self.min_indices = [idx for idx, x in enumerate(curr_arr) if x == self.current_min_val]
                        steps.append((self.get_arrays_snapshot(), 
                            f"Ініціалізація мінімуму: {vname} = {self.current_min_val}", 
                            self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                            self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                        ))
                    elif "count" in vname.lower() or "matched" in vname.lower() or "size" in vname.lower():
                        self.condition_count = int(val_eval)
                        self.current_size = int(val_eval)
                        steps.append((self.get_arrays_snapshot(), f"Кількість елементів: {vname} = {self.current_size}", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
                    elif "sum" in vname.lower():
                        steps.append((self.get_arrays_snapshot(), f"Обчислено суму: {vname} = {val_eval}", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
                    elif "avg" in vname.lower() or "mean" in vname.lower():
                        steps.append((self.get_arrays_snapshot(), f"Середнє арифметичне: {vname} = {val_eval:.2f}", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
            return

        # 2D vector row push_back: matrix[i].push_back(val)
        m_2d_push = re.match(r"^([a-zA-Z_]\w*)\s*\[([^\]]+)\]\.(?:push_back|emplace_back)\s*\((.+)\);?$", s)
        if m_2d_push:
            target_name = m_2d_push.group(1)
            row_idx = int(self.eval_expression(m_2d_push.group(2)))
            val = self.parse_num(self.eval_expression(m_2d_push.group(3)))
            if target_name in self.arrays and isinstance(self.arrays[target_name], list):
                mat = self.arrays[target_name]
                if 0 <= row_idx < len(mat) and isinstance(mat[row_idx], list):
                    mat[row_idx].append(val)
                    steps.append((
                        self.get_arrays_snapshot(),
                        f"{target_name}[{row_idx}].push_back({val})",
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                    return

        # 2D vector row pop_back: matrix[i].pop_back()
        m_2d_pop = re.match(r"^([a-zA-Z_]\w*)\s*\[([^\]]+)\]\.pop_back\s*\(\s*\);?$", s)
        if m_2d_pop:
            target_name = m_2d_pop.group(1)
            row_idx = int(self.eval_expression(m_2d_pop.group(2)))
            if target_name in self.arrays and isinstance(self.arrays[target_name], list):
                mat = self.arrays[target_name]
                if 0 <= row_idx < len(mat) and isinstance(mat[row_idx], list) and mat[row_idx]:
                    popped = mat[row_idx].pop()
                    steps.append((
                        self.get_arrays_snapshot(),
                        f"{target_name}[{row_idx}].pop_back() (вилучено {popped})",
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                    return

        # 2D vector push row: matrix.push_back({1, 2})
        m_push_row = re.match(r"^([a-zA-Z_]\w*)\.(?:push_back|emplace_back)\s*\(\s*(?:(?:std\s*::\s*)?vector\s*<[^>]+>\s*)?\{([^}]*)\}\s*\);?$", s)
        if m_push_row:
            target_name = m_push_row.group(1)
            if target_name in self.arrays and isinstance(self.arrays[target_name], list):
                row_vals = [self.parse_num(self.eval_expression(x)) for x in m_push_row.group(2).split(',') if x.strip()]
                self.arrays[target_name].append(row_vals)
                steps.append((
                    self.get_arrays_snapshot(),
                    f"{target_name}.push_back({{ {', '.join(map(str, row_vals))} }})",
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                ))
                return

        # 1D vector resize: v.resize(new_sz) or v.resize(new_sz, fill_val)
        m_resize = re.match(r"^([a-zA-Z_]\w*)\.resize\s*\(([^)]+)\);?$", s)
        if m_resize:
            target_name = m_resize.group(1)
            args = [a.strip() for a in m_resize.group(2).split(',')]
            new_sz = min(max(int(self.eval_expression(args[0])), 0), 25)
            fill_val = self.parse_num(self.eval_expression(args[1])) if len(args) > 1 else 0
            if target_name in self.arrays and isinstance(self.arrays[target_name], list):
                arr = self.arrays[target_name]
                old_sz = len(arr)
                if new_sz < old_sz:
                    self.arrays[target_name] = arr[:new_sz]
                elif new_sz > old_sz:
                    arr.extend([fill_val] * (new_sz - old_sz))
                self.main_array_name = target_name
                self.current_size = len(self.arrays[target_name])
                cap = max(self.vector_capacities.get(target_name, self.current_size), self.current_size)
                self.vector_capacities[target_name] = cap
                self.current_capacity = cap
                steps.append((
                    self.get_arrays_snapshot(),
                    f"{target_name}.resize({new_sz}) (розмір: {self.current_size}, місткість: {self.current_capacity})",
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                    True, self.current_capacity, self.current_size, None, None, None, None
                ))
                return

        # 1D vector reserve: v.reserve(new_cap)
        m_reserve = re.match(r"^([a-zA-Z_]\w*)\.reserve\s*\(([^)]+)\);?$", s)
        if m_reserve:
            target_name = m_reserve.group(1)
            new_cap = int(self.eval_expression(m_reserve.group(2)))
            if target_name in self.arrays:
                self.main_array_name = target_name
                cap = max(self.vector_capacities.get(target_name, 0), new_cap)
                self.vector_capacities[target_name] = cap
                self.current_capacity = cap
                self.current_size = len(self.arrays[target_name])
                steps.append((
                    self.get_arrays_snapshot(),
                    f"{target_name}.reserve({new_cap}) (місткість збільшено до {self.current_capacity})",
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                    True, self.current_capacity, self.current_size, None, None, None, None
                ))
                return

        # 1D vector shrink_to_fit: v.shrink_to_fit()
        m_shrink = re.match(r"^([a-zA-Z_]\w*)\.shrink_to_fit\s*\(\s*\);?$", s)
        if m_shrink:
            target_name = m_shrink.group(1)
            if target_name in self.arrays:
                self.main_array_name = target_name
                cap = len(self.arrays[target_name])
                self.vector_capacities[target_name] = cap
                self.current_capacity = cap
                self.current_size = len(self.arrays[target_name])
                steps.append((
                    self.get_arrays_snapshot(),
                    f"{target_name}.shrink_to_fit() (місткість зменшено до розміру: {self.current_capacity})",
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                    True, self.current_capacity, self.current_size, None, None, None, None
                ))
                return

        # 1D vector assign: v.assign(count, val)
        m_assign = re.match(r"^([a-zA-Z_]\w*)\.assign\s*\(([^)]+)\);?$", s)
        if m_assign:
            target_name = m_assign.group(1)
            args = [a.strip() for a in m_assign.group(2).split(',')]
            if len(args) == 2:
                count = min(max(int(self.eval_expression(args[0])), 0), 25)
                fill_val = self.parse_num(self.eval_expression(args[1]))
                if target_name in self.arrays:
                    self.arrays[target_name] = [fill_val] * count
                    self.main_array_name = target_name
                    self.current_size = count
                    cap = max(self.vector_capacities.get(target_name, 0), count)
                    self.vector_capacities[target_name] = cap
                    self.current_capacity = cap
                    steps.append((
                        self.get_arrays_snapshot(),
                        f"{target_name}.assign({count}, {fill_val})",
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                        True, self.current_capacity, self.current_size, None, None, None, None
                    ))
                    return

        arr = self.arrays[target_name]

        if f"{target_name}.back()" in s and "=" in s and arr:
            s = s.replace(f"{target_name}.back()", f"{target_name}[{len(arr)-1}]")

        if ".fill" in s:
            val_expr = s[s.find("(")+1:s.rfind(")")]
            val = self.parse_num(self.eval_expression(val_expr))
            for i in range(len(arr)):
                old = arr[i]
                arr[i] = val
                steps.append((self.get_arrays_snapshot(), f"{target_name}[{i}] = {val} (було {old})", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
            return

        if ".swap" in s:
            other_m = re.search(r"\.swap\s*\(\s*(\w+)\s*\)", s)
            if other_m:
                other_name = other_m.group(1)
                if other_name in self.arrays:
                    self.arrays[target_name], self.arrays[other_name] = self.arrays[other_name], self.arrays[target_name]
                    steps.append((self.get_arrays_snapshot(), f"Оголошено масив: {target_name}[{len(self.arrays[target_name])}]", self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair, self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None))
            return

        if ".push_back" in s or ".emplace_back" in s:
            val_expr = s[s.find("(")+1:s.rfind(")")]
            val = self.parse_num(self.eval_expression(val_expr))
            arr.append(val)
            self.current_size = len(arr)
            cap = self.vector_capacities.get(target_name, len(arr))
            if len(arr) > cap:
                cap = 1 if cap == 0 else cap * 2
                while len(arr) > cap:
                    cap *= 2
            self.vector_capacities[target_name] = cap
            self.current_capacity = cap
            steps.append((
                self.get_arrays_snapshot(),
                f"{target_name}.push_back({val}) (розмір: {self.current_size}, місткість: {self.current_capacity})",
                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, [len(arr)-1],
                True, self.current_capacity, self.current_size, None, None, None, None
            ))
            return

        if ".pop_back" in s and arr:
            popped = arr.pop()
            self.current_size = len(arr)
            cap = self.vector_capacities.get(target_name, len(arr))
            self.current_capacity = cap
            steps.append((
                self.get_arrays_snapshot(),
                f"{target_name}.pop_back() (вилучено {popped}, новий розмір: {self.current_size})",
                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                True, self.current_capacity, self.current_size, None, None, None, None
            ))
            return

        if ".clear" in s:
            arr.clear()
            self.current_size = 0
            cap = self.vector_capacities.get(target_name, 0)
            self.current_capacity = cap
            steps.append((
                self.get_arrays_snapshot(),
                f"{target_name}.clear() (розмір: 0, місткість: {self.current_capacity})",
                self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, None, None,
                True, self.current_capacity, self.current_size, None, None, None, None
            ))
            return

        if "=" in s:
            if isinstance(arr, list) and len(arr) > 0 and isinstance(arr[0], list):
                return
            lhs, rhs = s.split("=", 1)
            b_l = lhs.find("[")
            b_r = lhs.rfind("]")
            idx = 0
            if b_l != -1 and b_r != -1:
                idx = self.eval_int(lhs[b_l+1:b_r])
            elif ".at(" in lhs:
                b_l = lhs.find(".at(")
                b_r = lhs.find(")", b_l)
                idx = self.eval_int(lhs[b_l+4:b_r])
            
            val = self.parse_num(self.eval_expression(rhs))

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
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                    self.temp_val = None
                    self.active_pair = None
                elif is_shift_step:
                    pair = [idx, min(idx + 1, len(arr) - 1)]
                    shift_label = f"Зсув елемента праворуч: {target_name}[{idx}] = {val}" if "j" in lhs else f"Зсув елемента: {target_name}[{idx}] = {val}"
                    steps.append((
                        list(arr), 
                        shift_label, 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                elif "temp" in rhs.lower():
                    steps.append((
                        list(arr), 
                        f"Обмін / Сортування: {target_name}[{idx}] = temp ({val}). Завершено!", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                    self.temp_val = None
                    self.active_pair = None
                elif ("[" in rhs or ".at(" in rhs) and self.temp_val is not None:
                    steps.append((
                        list(arr), 
                        f"Обмін / Сортування: переміщення {target_name}[{idx}] = {val}", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
                else:
                    steps.append((
                        self.get_arrays_snapshot(), 
                        f"{target_name}[{idx}] = {val} (було {old})", 
                        self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                        self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                    ))
            elif idx == len(arr) and len(arr) < 25:
                arr.append(val)
                self.current_size = len(arr)
                steps.append((
                    self.get_arrays_snapshot(), 
                    f"Додано: {target_name}[{idx}] = {val}", 
                    self.has_sum_avg, self.condition_count, list(self.max_indices), self.current_max_val, self.temp_val, self.active_pair,
                    self.has_capacity_size, self.current_capacity, self.current_size, None, None, None, None
                ))
            return


class CodeVisualizer(QWidget):
    """Головний двопанельний віджет візуалізатора з прив'язкою затримки анімацій до швидкості відтворення."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Покрокова візуалізація масивів C++ (Масиви, std::vector та матриці)")

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

        self.anim_widget.set_animation_speed(400)
        self.timer.start(400)

    def process_next_step(self):
        if self.current_step >= len(self.steps_queue):
            self.timer.stop()
            return

        if self.current_step < len(self.steps_queue):
            step_data = self.steps_queue[self.current_step]
            if isinstance(step_data, dict):
                arr_state = step_data.get('arrays', {})
                desc = step_data.get('desc', '')
                show_sum_avg = step_data.get('show_sum_avg', True)
                cnt_metric = step_data.get('cnt_metric')
                max_indices = step_data.get('max_indices')
                max_val = step_data.get('max_val')
                temp_val = step_data.get('temp_val') if getattr(self.engine, 'has_temp_in_code', False) else None
                pair_indices = step_data.get('pair')
                show_capacity_size = step_data.get('show_capacity_size', False)
                cap_metric = step_data.get('cap_metric')
                sz_metric = step_data.get('sz_metric')
                search_idx = step_data.get('search_idx')
                found_idx = step_data.get('found_idx')
                bin_range = step_data.get('bin_range')
                bin_mid = step_data.get('bin_mid')
                pivot_idx = step_data.get('pivot_idx')
                min_val = step_data.get('min_val')
                min_indices = step_data.get('min_indices')
                extra_vars = step_data.get('extra_vars')
                precision = step_data.get('precision', 2)
            else:
                arr_state = step_data[0] if len(step_data) > 0 else {}
                desc = step_data[1] if len(step_data) > 1 else ""
                show_sum_avg = step_data[2] if len(step_data) > 2 else False
                cnt_metric = step_data[3] if len(step_data) > 3 else None
                max_indices = step_data[4] if len(step_data) > 4 else None
                max_val = step_data[5] if len(step_data) > 5 else None
                temp_val = (step_data[6] if len(step_data) > 6 else None) if getattr(self.engine, 'has_temp_in_code', False) else None
                pair_indices = step_data[7] if len(step_data) > 7 else None
                show_capacity_size = step_data[8] if len(step_data) > 8 else False
                cap_metric = step_data[9] if len(step_data) > 9 else None
                sz_metric = step_data[10] if len(step_data) > 10 else None
                search_idx = step_data[11] if len(step_data) > 11 else None
                found_idx = step_data[12] if len(step_data) > 12 else None
                bin_range = step_data[13] if len(step_data) > 13 else None
                bin_mid = step_data[14] if len(step_data) > 14 else None
                pivot_idx = step_data[15] if len(step_data) > 15 else None
                min_val = step_data[16] if len(step_data) > 16 else None
                min_indices = step_data[17] if len(step_data) > 17 else None
                extra_vars = step_data[18] if len(step_data) > 18 else None
                precision = step_data[19] if len(step_data) > 19 else 2

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
                found_index=found_idx,
                binary_range=bin_range,
                binary_mid=bin_mid,
                pivot_index=pivot_idx,
                current_min_val=min_val,
                min_indices=min_indices,
                extra_vars=extra_vars,
                precision=precision
            )
            self.current_step += 1


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CodeVisualizer()
    window.resize(1100, 650)
    window.show()
    sys.exit(app.exec_())
