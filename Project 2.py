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

        # Внутрішні атрибути для кольорів та шрифту
        self._bg_color = QColor(bg_color)
        self._text_color = QColor(text_color)
        self._border_color = QColor("#333333")
        self._font = QFont("Arial", 12)

    # --- Обов'язкові методи відмальовування (Крок 1 ТЗ) ---

    def boundingRect(self):
        """Визначає межі елемента на сцені (з урахуванням товщини контуру)."""
        pen_width = 1.0
        return QRectF(-pen_width / 2, -pen_width / 2, 
                      self._width + pen_width, self._height + pen_width)

    def paint(self, painter, option, widget=None):
        """Самостійне відмальовування прямокутника та тексту."""
        rect = QRectF(0, 0, self._width, self._height)

        # Малювання прямокутника
        painter.setPen(QPen(self._border_color, 1))
        painter.setBrush(QBrush(self._bg_color))
        painter.drawRect(rect)

        # Малювання тексту по центру
        painter.setPen(QPen(self._text_color))
        painter.setFont(self._font)
        painter.drawText(rect, Qt.AlignCenter, self._text)

    # --- Методи-сетери з обов'язковим self.update() ---

    def set_bg_color(self, color):
        """Зміна кольору фону з оновленням відображення."""
        self._bg_color = QColor(color)
        self.update()

    def set_text_color(self, color):
        """Зміна кольору тексту з оновленням відображення."""
        self._text_color = QColor(color)
        self.update()

    def set_text(self, text):
        """Оновлення тексту блока."""
        self._text = str(text)
        self.update()

    def set_border_color(self, color):
        """Оновлення кольору контуру."""
        self._border_color = QColor(color)
        self.update()


class CartoonAnimationHandler:
    """
    Клас-обробник мультяшних анімацій для блоків AnimatedArrayBlock 
    відповідно до сценаріїв А, Б та В.
    Тривалість анімацій налаштована на рівні <= 350 мс для синхронізації з кроками.
    """

    @staticmethod
    def animate_push_back(block_item, target_pos, duration=350):
        """
        Сценарій А: Додавання (push_back)
        - Поява нового блоку.
        - scale від 0.0 до 1.0 з ефектом відскоку (OutBounce).
        """
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
    def animate_pop(block_item, scene, duration=350):
        """
        Сценарій Б: Видалення (pop)
        - Зникнення останнього елемента.
        - QParallelAnimationGroup: scale до 0.0 та opacity до 0.0.
        - Видалення зі сцени по завершенню.
        """
        block_item.setTransformOriginPoint(block_item.boundingRect().center())

        group = QParallelAnimationGroup()

        # Зменшення розміру scale -> 0.0
        scale_anim = QPropertyAnimation(block_item, b"scale")
        scale_anim.setDuration(duration)
        scale_anim.setStartValue(block_item.scale())
        scale_anim.setEndValue(0.0)
        scale_anim.setEasingCurve(QEasingCurve.InBack)

        # Зникнення opacity -> 0.0
        opacity_anim = QPropertyAnimation(block_item, b"opacity")
        opacity_anim.setDuration(duration)
        opacity_anim.setStartValue(block_item.opacity())
        opacity_anim.setEndValue(0.0)
        opacity_anim.setEasingCurve(QEasingCurve.InQuad)

        group.addAnimation(scale_anim)
        group.addAnimation(opacity_anim)

        group.finished.connect(lambda: scene.removeItem(block_item))
        return group

    @staticmethod
    def animate_change(block_item, new_value, new_bg_color="#ff9999", duration=350):
        """
        Сценарій В: Зміна / Індексація
        - Підсвічування елемента.
        - Пульсація: scale 1.0 → 1.2 → 1.0.
        - Оновлення кольору/тексту.
        """
        block_item.setTransformOriginPoint(block_item.boundingRect().center())
        
        block_item.set_bg_color(new_bg_color)
        block_item.set_text(new_value)

        seq_group = QSequentialAnimationGroup()

        # Фаза 1: збільшення 1.0 -> 1.2
        grow_anim = QPropertyAnimation(block_item, b"scale")
        grow_anim.setDuration(duration // 2)
        grow_anim.setStartValue(1.0)
        grow_anim.setEndValue(1.2)
        grow_anim.setEasingCurve(QEasingCurve.OutQuad)

        # Фаза 2: повернення 1.2 -> 1.0
        shrink_anim = QPropertyAnimation(block_item, b"scale")
        shrink_anim.setDuration(duration // 2)
        shrink_anim.setStartValue(1.2)
        shrink_anim.setEndValue(1.0)
        shrink_anim.setEasingCurve(QEasingCurve.OutBack)

        seq_group.addAnimation(grow_anim)
        seq_group.addAnimation(shrink_anim)

        return seq_group


class AdaptiveAnimationWidget(QWidget):
    """
    Віджет єдиного динамічного горизонтального масиву на сцені.
    Керує станом об'єктів без постійного повного scene.clear().
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        # Поточний стан блоків: [{'item': AnimatedArrayBlock, 'value': val}, ...]
        self.current_array_blocks = []
        self.static_items = []

        # Геометрія розміщення елементів
        self.block_width = 65.0
        self.block_height = 40.0
        self.spacing = 8.0
        self.base_x = 50.0
        self.base_y = 120.0

        self.active_animation_group = None

    def reset(self):
        """Повне очищення віджета перед новим запуском."""
        if self.active_animation_group and self.active_animation_group.state() == QParallelAnimationGroup.Running:
            self.active_animation_group.stop()
        self.scene.clear()
        self.current_array_blocks.clear()
        self.static_items.clear()

    def clear_static_layer(self):
        """Очищення лише статичних текстових підписів."""
        for item in self.static_items:
            if item.scene() == self.scene:
                self.scene.removeItem(item)
        self.static_items.clear()

    def get_target_pos(self, index):
        x = self.base_x + index * (self.block_width + self.spacing)
        y = self.base_y
        return QPointF(x, y)

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

        # 1. Сценарій В: Зміна / Індексація існуючих елементів
        min_len = min(old_count, new_count)
        for i in range(min_len):
            block_data = self.current_array_blocks[i]
            block_item = block_data['item']
            old_val = block_data['value']
            new_val = new_values[i]

            if old_val != new_val:
                block_data['value'] = new_val
                pulse_anim = CartoonAnimationHandler.animate_change(
                    block_item, new_val, new_bg_color="#ff9999"
                )
                anim_group.addAnimation(pulse_anim)
            else:
                block_item.set_bg_color("#33ccff")

        # 2. Сценарій А: Додавання нових блоків (push_back)
        if new_count > old_count:
            for i in range(old_count, new_count):
                val = new_values[i]
                target_pos = self.get_target_pos(i)

                new_block = AnimatedArrayBlock(
                    text=val,
                    width=self.block_width,
                    height=self.block_height,
                    bg_color="#99ff99"
                )
                self.scene.addItem(new_block)

                bounce_anim = CartoonAnimationHandler.animate_push_back(
                    new_block, target_pos
                )
                anim_group.addAnimation(bounce_anim)

                self.current_array_blocks.append({
                    'item': new_block,
                    'value': val
                })

        # 3. Сценарій Б: Видалення зайвих блоків (pop)
        elif new_count < old_count:
            blocks_to_remove = self.current_array_blocks[new_count:]
            self.current_array_blocks = self.current_array_blocks[:new_count]

            for block_data in blocks_to_remove:
                block_item = block_data['item']
                block_item.set_bg_color("#e74c3c")

                pop_group = CartoonAnimationHandler.animate_pop(
                    block_item, self.scene
                )
                anim_group.addAnimation(pop_group)

        # Синхронізація позицій існуючих елементів
        for i, block_data in enumerate(self.current_array_blocks):
            if i < len(new_values):
                block_data['value'] = new_values[i]
                block_data['item'].set_text(new_values[i])
            target_pos = self.get_target_pos(i)
            if block_data['item'].pos() != target_pos:
                block_data['item'].setPos(target_pos)

        self.active_animation_group = anim_group
        anim_group.start()


class CodeVisualizer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Покрокова візуалізація масиву")

        main_layout = QHBoxLayout()
        self.setLayout(main_layout)

        # Ліва частина (редактор вихідного C++ коду)
        left_layout = QVBoxLayout()
        main_layout.addLayout(left_layout, 1)
        self.code_edit = QTextEdit()
        self.code_edit.setFont(QFont("Consolas", 12))
        self.code_edit.textChanged.connect(self.on_code_text_changed)
        left_layout.addWidget(self.code_edit)

        # Панель кнопок керування ("▶" та зупинка/скидання "⏹")
        button_layout = QVBoxLayout()
        main_layout.addLayout(button_layout)
        
        self.run_button = QPushButton("▶")
        self.run_button.setFixedSize(40, 40)
        self.run_button.setFont(QFont("Arial", 14, QFont.Bold))
        self.run_button.clicked.connect(self.run_visualization)
        button_layout.addWidget(self.run_button)

        # Кнопка безпечного переривання/скидання циклу (зауваження викладача)
        self.stop_button = QPushButton("⏹")
        self.stop_button.setFixedSize(40, 40)
        self.stop_button.setFont(QFont("Arial", 14, QFont.Bold))
        self.stop_button.setToolTip("Безпечне переривання / Скидання візуалізації")
        self.stop_button.clicked.connect(self.reset_visualizer)
        button_layout.addWidget(self.stop_button)

        button_layout.addStretch()

        # Права частина: використовуємо AdaptiveAnimationWidget
        self.anim_widget = AdaptiveAnimationWidget(self)
        main_layout.addWidget(self.anim_widget, 1)

        # Таймер із кроком 450 мс
        self.timer = QTimer()
        self.timer.timeout.connect(self.process_next_step)

        # Стан візуалізації та захист від зациклень
        self.current_array = []
        self.init_sub_idx = 0
        self.initial_values = []
        self.last_state_array = []
        self.executed_actions = []
        self.action_queue = []
        self.is_initialized = False
        self.var_name = "arr"
        self.last_var_name = ""
        
        # Захисні ліміти для запобігання надто довгим або нескінченним ітераціям
        self.max_steps_limit = 150
        self.current_step_count = 0

    def on_code_text_changed(self):
        code = self.code_edit.toPlainText().strip()
        if not code:
            self.reset_visualizer()

    def reset_visualizer(self):
        """Безпечне примусове завершення / скидання стану візуалізатора."""
        self.timer.stop()
        self.anim_widget.reset()
        self.current_array = []
        self.init_sub_idx = 0
        self.initial_values = []
        self.last_state_array = []
        self.executed_actions = []
        self.action_queue = []
        self.is_initialized = False
        self.last_var_name = ""
        self.current_step_count = 0

    def parse_cpp_code(self):
        code = self.code_edit.toPlainText()
        code_clean = re.sub(r"//.*", "", code)
        code_clean = re.sub(r"/\*.*?\*/", "", code_clean, flags=re.DOTALL)

        constants = {}
        const_matches = re.findall(r"(?:const\s+int|int)\s+(\w+)\s*=\s*(\d+)\s*;", code_clean)
        for name, val in const_matches:
            constants[name] = int(val)

        initial_values = []
        var_name = "arr"
        declared_size = 5

        size_match = re.search(r"(?:int\s+size|int\s+capacity)\s*=\s*(\w+|\d+)\s*;", code_clean)
        if size_match:
            s_val = size_match.group(1)
            declared_size = constants.get(s_val, int(s_val) if s_val.isdigit() else 10)

        decl_match = re.search(r"(?:vector\s*<\s*\w+\s*>|(?:int\*))\s+(\w+)", code_clean)
        if decl_match:
            var_name = decl_match.group(1)

        loop_match = re.search(r"for\s*\(\s*int\s+\w+\s*=\s*0\s*;\s*\w+\s*<\s*(\w+|\d+)[^;]*;[^)]+\)\s*\{([^}]+)\}", code_clean, re.DOTALL)
        if loop_match:
            limit_str = loop_match.group(1)
            limit = constants.get(limit_str, int(limit_str) if limit_str.isdigit() else declared_size)
            # Захист: обмежуємо максимальну кількість елементів у циклі до безпечного рівня
            limit = min(limit, 30)
            generated = [random.randint(1, 100) for _ in range(limit)]
            initial_values = generated
        else:
            initial_values = [random.randint(1, 100) for _ in range(min(declared_size, 30))]

        actions = []
        lines = code_clean.split('\n')
        
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            if "push_back" in line_str or "emplace_back" in line_str:
                actions.append(("push", var_name, random.randint(1, 100), line_str))
                continue

            resize_match = re.search(r"resize\s*\(\s*(\d+)\s*\)", line_str)
            if resize_match:
                new_sz = min(int(resize_match.group(1)), 30)
                actions.append(("resize", var_name, new_sz, line_str))
                continue

            if "insert" in line_str:
                actions.append(("insert", var_name, random.randint(1, 100), line_str))
                continue

            if "pop_back" in line_str or "erase" in line_str or "smaller" in line_str:
                actions.append(("pop", var_name, None, line_str))
                continue

            assign_match = re.search(r"(\w+)\s*\[\s*(\w+|\d+)\s*\]\s*=\s*([^;]+);", line_str)
            if assign_match:
                idx_str = assign_match.group(2)
                idx = constants.get(idx_str, int(idx_str) if idx_str.isdigit() else 0)
                actions.append(("set", var_name, idx, random.randint(1, 100), line_str))
                continue

        return initial_values, actions, var_name

    def run_visualization(self):
        code_text = self.code_edit.toPlainText().strip()
        if not code_text:
            self.reset_visualizer()
            return

        self.timer.stop()
        init_vals, current_all_actions, var_name = self.parse_cpp_code()
        self.var_name = var_name

        if not self.is_initialized or (self.last_var_name and self.last_var_name != var_name):
            self.anim_widget.reset()
            self.init_sub_idx = 0
            self.initial_values = init_vals
            self.current_array = []
            self.last_state_array = list(init_vals)
            self.executed_actions = []
            self.action_queue = list(current_all_actions)
            self.last_var_name = var_name
            self.is_initialized = True
            self.current_step_count = 0
        else:
            self.action_queue = current_all_actions

        if not self.initial_values and not self.action_queue:
            return

        self.timer.start(450)

    def process_next_step(self):
        # Захист від зациклень та занадто довгих ітерацій (зауваження викладача)
        self.current_step_count += 1
        if self.current_step_count > self.max_steps_limit:
            self.timer.stop()
            self.anim_widget.update_variables(
                self.current_array, 
                step_description="[Безпечний вихід]: Досягнуто ліміту ітерацій циклу / автомата."
            )
            return

        # 1. Покрокове заповнення початкових елементів масиву
        if self.init_sub_idx < len(self.initial_values):
            val = self.initial_values[self.init_sub_idx]
            self.current_array.append(val)
            self.anim_widget.update_variables(
                self.current_array, 
                step_description=f"Ініціалізація: {self.var_name}[{self.init_sub_idx}] = {val}"
            )
            self.init_sub_idx += 1
            return

        # 2. Покрокове виконання подальших дій над динамічним масивом
        if self.action_queue:
            action = self.action_queue.pop(0)
            self.executed_actions.append(action)

            action_type = action[0]
            if action_type == "push":
                _, var_name, val, _ = action
                self.current_array.append(val)
                label_text = f"push_back / додавання: додано елемент {val}"

            elif action_type == "resize":
                _, var_name, new_sz, _ = action
                while len(self.current_array) < new_sz:
                    self.current_array.append(random.randint(1, 100))
                while len(self.current_array) > new_sz:
                    self.current_array.pop()
                label_text = f"resize({new_sz}): змінено розмір динамічного масиву"

            elif action_type == "insert":
                _, var_name, val, _ = action
                pos = len(self.current_array) // 2
                self.current_array.insert(pos, val)
                label_text = f"Вставка у позицію [{pos}] значення {val} (зсув)"

            elif action_type == "pop":
                removed = self.current_array.pop() if self.current_array else None
                label_text = f"Видалення елемента (pop/erase): видалено {removed}"

            elif action_type == "set":
                _, var_name, idx, val, _ = action
                if idx < len(self.current_array):
                    old_val = self.current_array[idx]
                    self.current_array[idx] = val
                    label_text = f"Зміна: {var_name}[{idx}] = {old_val} → {val}"
                else:
                    label_text = f"Оновлення елемента за індексом [{idx}]"

            self.anim_widget.update_variables(self.current_array, step_description=label_text)
        else:
            self.timer.stop()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = CodeVisualizer()
    w.resize(1050, 750)
    w.show()
    sys.exit(app.exec_())
