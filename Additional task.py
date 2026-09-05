import copy
import math
import os
import sys
import io
import re
import ast
import time
import json
import shutil
import traceback

# --- Налаштування контексту до створення QApplication ---
from PyQt6.QtCore import Qt, QCoreApplication
try:
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
except Exception:
    pass

# --- PyQt6 ---
from PyQt6.QtWidgets import (
    QApplication, QGraphicsPolygonItem, QGraphicsRectItem, QGraphicsTextItem,
    QMainWindow, QStatusBar, QWidget, QVBoxLayout, QPushButton, QToolTip,
    QPlainTextEdit, QListView, QGraphicsView, QGraphicsScene,
    QSplitter, QTabWidget, QToolBar, QLabel, QTextEdit,
    QInputDialog, QFileDialog, QMessageBox, QProgressBar, QDockWidget, QTreeView,
)
from PyQt6.QtGui import (
    QAction, QFont, QColor, QPainter, QPainterPath, QPolygonF, QTextCursor, QTextCharFormat, QSyntaxHighlighter,
    QPixmap, QPen, QBrush, QPalette,
    QFileSystemModel, QWheelEvent
)
from PyQt6.QtCore import (
    QTimer, QSize, QRect, QPoint, QPointF, QDir, QUrl, pyqtSignal,
    QThread, QRegularExpression, QStringListModel,
)

# --- Зовнішні бібліотеки ---
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except (ImportError, Exception):
    QWebEngineView = None

try:
    import docx
except ImportError:
    docx = None

try:
    from pptx import Presentation
except ImportError:
    Presentation = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

try:
    import jedi
except ImportError:
    jedi = None


# --- Підсвічування синтаксису Python ---
class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = []

        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#CC7832"))
        keyword_format.setFontWeight(QFont.Weight.Bold)
        keywords = [
            "def", "class", "import", "from", "as", "if", "elif", "else", "while",
            "for", "try", "except", "finally", "return", "pass", "raise", "in",
            "not", "and", "or", "is", "with", "lambda", "yield",
            "True", "False", "None"
        ]
        for kw in keywords:
            pattern = QRegularExpression(r'\b' + kw + r'\b')
            self.rules.append((pattern, keyword_format))

        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#6A9955"))
        comment_pattern = QRegularExpression(r"#.*")
        self.rules.append((comment_pattern, comment_format))

        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#CE9178"))
        self.rules.append((QRegularExpression(r'"[^"\n]*"'), string_format))
        self.rules.append((QRegularExpression(r"'[^'\n]*'"), string_format))

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                match = it.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


# --- Область номерів рядків та точок зупинки ---
class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.code_editor = editor

    def sizeHint(self):
        return QSize(self.code_editor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event):
        self.code_editor.lineNumberAreaPaintEvent(event)


# --- Головний редактор коду ---
class CodeEditor(QPlainTextEdit):
    breakpointToggled = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setStyleSheet("background-color: #2b2b2b; color: #eeeeee; font: 11pt Consolas;")
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)
        self.line_number_area = LineNumberArea(self)

        self.breakpoint_lines = set()
        self.highlight_current_line_color = QColor("#3c3f41")
        self.ghost_text = ""
        self.ghost_active = False
        self.next_line_suggestions = {
            "if": "pass", "elif": "pass", "else": "pass",
            "for": "print(i)", "while": "break", "try": "pass",
            "except": "print(e)", "finally": "pass", "def": "return None",
            "class": "def __init__(self):", "with": "pass"
        }

        self.highlighter = PythonHighlighter(self.document())

        self.blockCountChanged.connect(self.updateLineNumberAreaWidth)
        self.updateRequest.connect(self.updateLineNumberArea)
        self.cursorPositionChanged.connect(self.highlightCurrentLine)
        self.cursorPositionChanged.connect(self.show_function_tooltip)

        self.updateLineNumberAreaWidth(0)

        self.auto_pass_timer = QTimer()
        self.auto_pass_timer.setSingleShot(True)
        self.auto_pass_timer.timeout.connect(self.insert_pass_if_empty)

        self.completer = None
        self.setup_completer()
        self.setMouseTracking(True)

    def setup_completer(self):
        self.completer = QListView()
        self.completer.setWindowFlags(Qt.WindowType.Popup)
        self.completer.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.completer.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.completer.setUniformItemSizes(True)
        self.completer_model = QStringListModel()
        self.completer.setModel(self.completer_model)
        self.completer.clicked.connect(self.complete_text)
        self.completer.hide()

    def complete_text(self, index):
        completion = self.completer_model.data(index, Qt.ItemDataRole.DisplayRole)
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        cursor.removeSelectedText()
        cursor.insertText(completion)
        self.setTextCursor(cursor)
        self.completer.hide()
        self.ghost_text = ""
        self.ghost_active = False

    def update_completions(self):
        try:
            if jedi is None:
                return
            cursor = self.textCursor()
            pos = cursor.position()
            code = self.toPlainText()
            lines = code[:pos].splitlines()
            row = len(lines)
            col = len(lines[-1]) if lines else 0

            script = jedi.Script(code, row, col)
            completions = [c.name for c in script.complete()]
            ast_items = self.analyze_ast(code)
            merged = list(set(completions + ast_items['functions'] + ast_items['classes'] + ast_items['variables']))
            merged.sort()

            prefix = self.text_under_cursor()
            filtered = [w for w in merged if w.startswith(prefix) and w != prefix]

            if filtered:
                self.completer_model.setStringList(filtered)
                cr = self.cursorRect()
                cr.setWidth(self.completer.sizeHintForColumn(0)
                            + self.completer.verticalScrollBar().sizeHint().width())
                self.completer.setGeometry(cr)
                self.completer.move(self.mapToGlobal(cr.bottomLeft()))
                self.completer.show()
            else:
                self.completer.hide()
        except Exception:
            self.completer.hide()

    def text_under_cursor(self):
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        return cursor.selectedText()

    def analyze_ast(self, code):
        try:
            tree = ast.parse(code)
            funcs, classes, vars_set = [], [], set()
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    funcs.append(node.name)
                elif isinstance(node, ast.ClassDef):
                    classes.append(node.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            vars_set.add(target.id)
            return {"functions": funcs, "classes": classes, "variables": list(vars_set)}
        except Exception:
            return {"functions": [], "classes": [], "variables": []}

    def keyPressEvent(self, event):
        if self.completer.isVisible():
            if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab):
                self.complete_text(self.completer.currentIndex())
                event.accept()
                return
            elif event.key() == Qt.Key.Key_Escape:
                self.completer.hide()
                event.accept()
                return

        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)

        if self.ghost_active and self.ghost_text and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Right):
            cursor.insertText(self.ghost_text)
            self.ghost_text = ""
            self.ghost_active = False
            self.completer.hide()
            return

        if event.key() == Qt.Key.Key_Return:
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            current_line = cursor.selectedText()
            indent = re.match(r"\s*", current_line).group()
            super().keyPressEvent(event)
            self.insertPlainText(indent)

            if current_line.rstrip().endswith(':'):
                self.insertPlainText("    ")
                words = current_line.strip().split()
                keyword = words[0] if words else ""
                suggestion = self.next_line_suggestions.get(keyword)
                if suggestion:
                    self.ghost_text = suggestion
                    self.ghost_active = True
                    self.update()
                    self.auto_pass_timer.start(1000)
                    return

        self.ghost_text = ""
        self.ghost_active = False
        self.auto_pass_timer.stop()

        super().keyPressEvent(event)
        self.update_completions()

    def insert_pass_if_empty(self):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        if not cursor.selectedText().strip():
            cursor.insertText("pass")

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.ghost_active and self.ghost_text:
            painter = QPainter(self.viewport())
            painter.setPen(QColor(150, 150, 150, 120))
            font = self.font()
            font.setItalic(True)
            painter.setFont(font)
            rect = self.cursorRect(self.textCursor())
            painter.drawText(rect.topRight() + QPoint(5, self.fontMetrics().ascent()), self.ghost_text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height()))

    def lineNumberAreaWidth(self):
        digits = len(str(max(1, self.blockCount())))
        space = 16 + self.fontMetrics().horizontalAdvance('9') * digits
        return space

    def updateLineNumberAreaWidth(self, _):
        self.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)

    def updateLineNumberArea(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())

        if rect.contains(self.viewport().rect()):
            self.updateLineNumberAreaWidth(0)

    def lineNumberAreaPaintEvent(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#313335"))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).y()
        bottom = top + self.blockBoundingRect(block).height()
        height = self.fontMetrics().height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                if block_number in self.breakpoint_lines:
                    painter.setBrush(QColor("#FF5555"))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(0, int(top + 4), 8, 8)
                painter.setPen(QColor("#888"))
                painter.drawText(0, int(top), self.lineNumberAreaWidth() - 4, height, Qt.AlignmentFlag.AlignRight, number)

            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_number += 1

    def highlightCurrentLine(self):
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(self.highlight_current_line_color)
            selection.format.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            self.setExtraSelections([selection])

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().x() < self.lineNumberAreaWidth():
            block = self.firstVisibleBlock()
            top = self.blockBoundingGeometry(block).translated(self.contentOffset()).y()
            bottom = top + self.blockBoundingRect(block).height()
            y = event.position().y()
            while block.isValid():
                if y >= top and y <= bottom:
                    line = block.blockNumber()
                    if line in self.breakpoint_lines:
                        self.breakpoint_lines.remove(line)
                    else:
                        self.breakpoint_lines.add(line)
                    self.line_number_area.update()
                    self.breakpointToggled.emit(line + 1)
                    break
                block = block.next()
                top = bottom
                bottom = top + self.blockBoundingRect(block).height()
        else:
            super().mousePressEvent(event)

    def show_function_tooltip(self):
        try:
            if jedi is None:
                return
            cursor = self.textCursor()
            pos = cursor.position()
            code = self.toPlainText()
            lines = code[:pos].splitlines()
            row = len(lines)
            col = len(lines[-1]) if lines else 0

            script = jedi.Script(code, row, col)
            sigs = script.get_signatures()
            if not sigs:
                QToolTip.hideText()
                return

            sig = sigs[0]
            params = [p.name for p in sig.params]
            call_text = self._get_current_function_call()
            arg_index = call_text.count(',')

            highlighted_params = []
            for i, p in enumerate(params):
                if i == arg_index:
                    highlighted_params.append(f"<b>{p}</b>")
                else:
                    highlighted_params.append(p)

            tooltip = f"<b>{sig.name}</b>({', '.join(highlighted_params)})"
            doc = sig.docstring()
            if doc:
                doc_line = doc.split('\n')[0]
                tooltip += f"<br><span style='color:#AAAAAA;'>{doc_line}</span>"

            QToolTip.showText(self.mapToGlobal(self.cursorRect().bottomRight()), tooltip, self)
        except Exception:
            QToolTip.hideText()

    def _get_current_function_call(self):
        code = self.toPlainText()
        pos = self.textCursor().position()
        stack = 0
        i = pos - 1
        while i >= 0:
            if code[i] == ')':
                stack += 1
            elif code[i] == '(':
                if stack == 0:
                    break
                stack -= 1
            i -= 1
        return code[i + 1:pos]


# --- Потоковий виконавець коду ---
class CodeRunner(QThread):
    output_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal()
    variable_update_signal = pyqtSignal(dict, dict)

    def __init__(self, code, step_delay=0.45):
        super().__init__()
        self.code = code
        self.step_delay = step_delay
        self.running = True
        self.paused = False

        self.meta_info = {
            "has_loops": False,
            "classes": {}
        }

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stop(self):
        self.running = False

    def _analyze_and_instrument(self, tree: ast.AST) -> ast.AST:
        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.While)):
                self.meta_info["has_loops"] = True
            elif isinstance(node, ast.ClassDef):
                base_name = "object"
                if node.bases:
                    if isinstance(node.bases[0], ast.Name):
                        base_name = node.bases[0].id
                self.meta_info["classes"][node.name] = base_name

        class UniversalStepInjector(ast.NodeTransformer):
            def _create_step_call(self):
                return ast.Expr(
                    value=ast.Call(
                        func=ast.Name(id='__universal_step_hook__', ctx=ast.Load()),
                        args=[],
                        keywords=[]
                    )
                )

            def _wrap_body(self, body_list):
                new_body = []
                for stmt in body_list:
                    transformed_stmt = self.visit(stmt)
                    new_body.append(transformed_stmt)
                    new_body.append(self._create_step_call())
                return new_body

            def visit_Module(self, node):
                node.body = self._wrap_body(node.body)
                return node

            def visit_For(self, node):
                node.body = self._wrap_body(node.body)
                return node

            def visit_While(self, node):
                node.body = self._wrap_body(node.body)
                return node

            def visit_If(self, node):
                node.body = self._wrap_body(node.body)
                if node.orelse:
                    node.orelse = self._wrap_body(node.orelse)
                return node

        transformer = UniversalStepInjector()
        transformed_tree = transformer.visit(tree)
        ast.fix_missing_locations(transformed_tree)
        return transformed_tree

    def run(self):
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = sys.stdout

        loc = {}
        glob = {"__name__": "__main__"}

        def universal_step_hook():
            if not self.running:
                raise KeyboardInterrupt("Execution stopped")

            while self.paused:
                time.sleep(0.05)

            user_vars = {}
            for k, v in loc.items():
                if not k.startswith("__"):
                    if isinstance(v, list):
                        user_vars[k] = copy.deepcopy(v)
                    else:
                        user_vars[k] = v

            if user_vars or self.meta_info["classes"]:
                self.variable_update_signal.emit(user_vars, self.meta_info)

                output = sys.stdout.getvalue()
                if output:
                    self.output_signal.emit(output)
                    sys.stdout.seek(0)
                    sys.stdout.truncate(0)

                sleep_steps = int(max(1, self.step_delay / 0.05))
                for _ in range(sleep_steps):
                    if not self.running:
                        break
                    while self.paused:
                        time.sleep(0.05)
                    time.sleep(self.step_delay / sleep_steps)

        glob["__universal_step_hook__"] = universal_step_hook

        try:
            self.progress_signal.emit(20)
            parsed_ast = ast.parse(self.code)
            instrumented_ast = self._analyze_and_instrument(parsed_ast)
            code_obj = compile(instrumented_ast, '<animated_code>', 'exec')

            self.progress_signal.emit(50)
            exec(code_obj, glob, loc)
            self.progress_signal.emit(100)

            final_output = sys.stdout.getvalue()
            if final_output:
                self.output_signal.emit(final_output)

        except KeyboardInterrupt:
            self.output_signal.emit("\n⏹ Виконання зупинено.")
        except Exception:
            self.output_signal.emit("❌ Помилка виконання:\n" + traceback.format_exc())
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            self.finished_signal.emit()


# --- Адаптивний віджет візуалізації ---
class AdaptiveAnimationWidget(QWidget):
    VARIABLE_TERMS = {
        "i": "Зовнішній лічильник",
        "j": "Внутрішній лічильник",
        "k": "Додатковий індекс",
        "min_index": "Індекс мінімуму",
        "max_index": "Індекс максимуму",
        "temp": "Тимчасова змінна",
        "key": "Опорний елемент",
        "count": "Лічильник",
        "total": "Сума",
        "result": "Результат",
    }

    def __init__(self, parent=None):
        super().__init__(parent)

        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setStyleSheet("background-color: #ffffff; border: 1px solid #cbd5e0; border-radius: 6px;")

        layout = QVBoxLayout()
        layout.addWidget(self.view)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

    def _draw_arrow(self, x1, y1, x2, y2, color="#000000", width=2):
        self.scene.addLine(x1, y1, x2, y2, QPen(QColor(color), width))
        angle = math.atan2(y2 - y1, x2 - x1)
        arrow_size = 8
        p1 = QPointF(x2, y2)
        p2 = QPointF(x2 - arrow_size * math.cos(angle - math.pi / 6), y2 - arrow_size * math.sin(angle - math.pi / 6))
        p3 = QPointF(x2 - arrow_size * math.cos(angle + math.pi / 6), y2 - arrow_size * math.sin(angle + math.pi / 6))
        
        arrow_head = QGraphicsPolygonItem(QPolygonF([p1, p2, p3]))
        arrow_head.setBrush(QBrush(QColor(color)))
        arrow_head.setPen(QPen(QColor(color)))
        self.scene.addItem(arrow_head)

    def _draw_diamond(self, cx, cy, w, h, text_str, bg_color="#FEFCBF", border_color="#B7791F"):
        p_top = QPointF(cx, cy - h / 2)
        p_right = QPointF(cx + w / 2, cy)
        p_bottom = QPointF(cx, cy + h / 2)
        p_left = QPointF(cx - w / 2, cy)

        diamond = QGraphicsPolygonItem(QPolygonF([p_top, p_right, p_bottom, p_left]))
        diamond.setBrush(QBrush(QColor(bg_color)))
        diamond.setPen(QPen(QColor(border_color), 2))
        self.scene.addItem(diamond)

        text = QGraphicsTextItem(text_str)
        text.setDefaultTextColor(QColor("#000000"))
        text.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        text.setPos(cx - text.boundingRect().width() / 2, cy - text.boundingRect().height() / 2)
        self.scene.addItem(text)

    def _draw_parallelogram(self, x, y, w, h, text_str, bg_color="#EDF2F7", border_color="#718096"):
        skew = 16
        p1 = QPointF(x + skew, y)
        p2 = QPointF(x + w, y)
        p3 = QPointF(x + w - skew, y + h)
        p4 = QPointF(x, y + h)

        poly = QGraphicsPolygonItem(QPolygonF([p1, p2, p3, p4]))
        poly.setBrush(QBrush(QColor(bg_color)))
        poly.setPen(QPen(QColor(border_color), 1.8))
        self.scene.addItem(poly)

        text = QGraphicsTextItem(text_str)
        text.setDefaultTextColor(QColor("#000000"))
        text.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        text.setPos(x + w / 2 - text.boundingRect().width() / 2, y + h / 2 - text.boundingRect().height() / 2)
        self.scene.addItem(text)

    def _draw_class_tree(self, classes_dict: dict, start_y: int, cx: int):
        tree = {}
        for child, parent in classes_dict.items():
            tree.setdefault(parent, []).append(child)

        roots = [p for p in tree.keys() if p not in classes_dict or classes_dict[p] == "object"]
        if not roots:
            roots = ["object"]

        box_w, box_h = 130, 42
        level_gap = 55

        # Рівень 0: Object
        root_name = "Object"
        obj_x = cx - box_w / 2
        obj_rect = QGraphicsRectItem(obj_x, start_y, box_w, box_h)
        obj_rect.setBrush(QBrush(QColor("#FFFFFF")))
        obj_rect.setPen(QPen(QColor("#000000"), 1.8))
        self.scene.addItem(obj_rect)

        t_obj = QGraphicsTextItem(root_name)
        t_obj.setDefaultTextColor(QColor("#000000"))
        t_obj.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        t_obj.setPos(obj_x + (box_w - t_obj.boundingRect().width()) / 2, start_y + 8)
        self.scene.addItem(t_obj)

        # Рівень 1: Базовий клас (Animal)
        user_bases = [cls for cls in classes_dict.keys() if classes_dict[cls].lower() == "object" or cls in roots]
        if not user_bases:
            user_bases = list(classes_dict.keys())[:1]

        y_lvl1 = start_y + box_h + level_gap
        self.scene.addLine(cx, start_y + box_h, cx, y_lvl1, QPen(QColor("#000000"), 1.8))

        base_name = user_bases[0] if user_bases else "Animal"
        base_x = cx - box_w / 2
        base_rect = QGraphicsRectItem(base_x, y_lvl1, box_w, box_h)
        base_rect.setBrush(QBrush(QColor("#FFFFFF")))
        base_rect.setPen(QPen(QColor("#000000"), 1.8))
        self.scene.addItem(base_rect)

        t_base = QGraphicsTextItem(base_name)
        t_base.setDefaultTextColor(QColor("#800000"))
        t_base.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        t_base.setPos(base_x + (box_w - t_base.boundingRect().width()) / 2, y_lvl1 + 8)
        self.scene.addItem(t_base)

        # Рівень 2: Нащадки (Cat, Mouse, Duck...)
        subclasses = [cls for cls, parent in classes_dict.items() if parent == base_name or (cls != base_name and parent.lower() != "object")]
        if not subclasses:
            subclasses = [cls for cls in classes_dict.keys() if cls != base_name]

        if subclasses:
            y_lvl2 = y_lvl1 + box_h + level_gap
            num_subs = len(subclasses)
            gap = 25
            total_w = num_subs * box_w + (num_subs - 1) * gap
            start_sub_x = cx - total_w / 2

            branch_y = y_lvl1 + box_h + level_gap / 2
            self.scene.addLine(cx, y_lvl1 + box_h, cx, branch_y, QPen(QColor("#000000"), 1.8))

            first_cx = start_sub_x + box_w / 2
            last_cx = start_sub_x + (num_subs - 1) * (box_w + gap) + box_w / 2
            self.scene.addLine(first_cx, branch_y, last_cx, branch_y, QPen(QColor("#000000"), 1.8))

            for i, sub_name in enumerate(subclasses):
                sub_cx = start_sub_x + i * (box_w + gap) + box_w / 2
                sub_x = sub_cx - box_w / 2

                self.scene.addLine(sub_cx, branch_y, sub_cx, y_lvl2, QPen(QColor("#000000"), 1.8))

                sub_rect = QGraphicsRectItem(sub_x, y_lvl2, box_w, box_h)
                sub_rect.setBrush(QBrush(QColor("#FFFFFF")))
                sub_rect.setPen(QPen(QColor("#000000"), 1.8))
                self.scene.addItem(sub_rect)

                t_sub = QGraphicsTextItem(sub_name)
                t_sub.setDefaultTextColor(QColor("#000000"))
                t_sub.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
                t_sub.setPos(sub_x + (box_w - t_sub.boundingRect().width()) / 2, y_lvl2 + 8)
                self.scene.addItem(t_sub)

    def update_variables(self, variables: dict, meta_info: dict):
        self.scene.clear()

        has_classes = bool(meta_info.get("classes"))
        has_loops = meta_info.get("has_loops", False)

        cx = max(380, self.view.width() // 2)
        y = 25

        # 1. ВЕРХНЯ ЧАСТИНА: Масиви / Списки
        highlighted_indices = {}
        if "j" in variables and isinstance(variables["j"], int):
            highlighted_indices[variables["j"]] = ("#ECC94B", "#B7791F")
        if "i" in variables and isinstance(variables["i"], int):
            if variables["i"] not in highlighted_indices:
                highlighted_indices[variables["i"]] = ("#ECC94B", "#B7791F")
        if "min_index" in variables and isinstance(variables["min_index"], int):
            highlighted_indices[variables["min_index"]] = ("#ED8936", "#C05621")

        for name, value in variables.items():
            if isinstance(value, list):
                arr_len = len(value)
                elem_w = 68
                elem_h = 42
                total_w = arr_len * elem_w
                start_x = cx - total_w / 2

                lbl = QGraphicsTextItem(f"Масив / Список: {name} (довжина {arr_len})")
                lbl.setDefaultTextColor(QColor("#000000"))
                lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
                lbl.setPos(start_x, y - 24)
                self.scene.addItem(lbl)

                for idx, elem in enumerate(value):
                    rx = start_x + idx * elem_w
                    if idx in highlighted_indices:
                        bg_hex, border_hex = highlighted_indices[idx]
                        bg_col = QColor(bg_hex)
                        border_col = QColor(border_hex)
                        p_width = 2.5
                    else:
                        bg_col = QColor("#68D391")
                        border_col = QColor("#22543D")
                        p_width = 1.5

                    rect = QGraphicsRectItem(rx, y, elem_w, elem_h)
                    rect.setBrush(QBrush(bg_col))
                    rect.setPen(QPen(border_col, p_width))
                    self.scene.addItem(rect)

                    t = QGraphicsTextItem(str(elem))
                    t.setDefaultTextColor(QColor("#000000"))
                    t.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
                    t.setPos(rx + 10, y + 8)
                    self.scene.addItem(t)

                    idx_lbl = QGraphicsTextItem(f"[{idx}]")
                    idx_lbl.setDefaultTextColor(QColor("#C53030"))
                    idx_lbl.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
                    idx_lbl.setPos(rx + elem_w / 2 - 12, y + elem_h + 2)
                    self.scene.addItem(idx_lbl)

                y += elem_h + 40

        # 2. НИЖНЯ ЧАСТИНА: АДАПТИВНИЙ РЕЖИМ
        if has_classes:
            # --- РЕЖИМ 1: ДЕРЕВО КЛАСІВ (ООП) ---
            title = QGraphicsTextItem("Ієрархія класів (ООП)")
            title.setDefaultTextColor(QColor("#004085"))
            title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            title.setPos(cx - title.boundingRect().width() / 2, y - 10)
            self.scene.addItem(title)

            self._draw_class_tree(meta_info["classes"], y + 20, cx)

        elif has_loops:
            # --- РЕЖИМ 2: БЛОК-СХЕМА ЦИКЛУ З ОПИСАМИ ЧАСТИН ---
            loop_var = "i"
            if "j" in variables:
                loop_var = "j"
            elif "i" in variables:
                loop_var = "i"
            elif "count" in variables:
                loop_var = "count"

            loop_val = variables.get(loop_var, 0)
            list_obj = next((v for v in variables.values() if isinstance(v, list)), None)
            limit_val = len(list_obj) if list_obj is not None else 5

            # 1. Початок циклу (Ініціалізація)[cite: 4]
            b1_w, b1_h = 180, 40
            b1_x = cx - b1_w / 2
            rect1 = QGraphicsRectItem(b1_x, y, b1_w, b1_h)
            rect1.setBrush(QBrush(QColor("#BEE3F8")))
            rect1.setPen(QPen(QColor("#2B6CB0"), 1.8))
            self.scene.addItem(rect1)

            t1 = QGraphicsTextItem(f"Початок: {loop_var} = {loop_val}")
            t1.setDefaultTextColor(QColor("#000000"))
            t1.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            t1.setPos(b1_x + 15, y + 8)
            self.scene.addItem(t1)

            # Опис блоку 1
            desc1 = QGraphicsTextItem("◀ Вхід / Ініціалізація лічильника")
            desc1.setDefaultTextColor(QColor("#4A5568"))
            desc1.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            desc1.setPos(b1_x + b1_w + 10, y + 10)
            self.scene.addItem(desc1)

            # Стрілка вниз до ромба[cite: 4]
            self._draw_arrow(cx, y + b1_h, cx, y + b1_h + 30)

            # 2. Ромб умови циклу[cite: 4]
            d_cy = y + b1_h + 30 + 35
            d_w, d_h = 150, 70
            self._draw_diamond(cx, d_cy, d_w, d_h, f"{loop_var} < {limit_val} ?")

            # Опис ромба
            desc_diamond = QGraphicsTextItem("◀ Умова продовження циклу")
            desc_diamond.setDefaultTextColor(QColor("#4A5568"))
            desc_diamond.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            desc_diamond.setPos(cx + d_w / 2 + 10, d_cy - 35)
            self.scene.addItem(desc_diamond)

            # --- ГІЛКА «ТАК (True)» ВНИЗ[cite: 4] ---
            lbl_yes = QGraphicsTextItem("Так (True)")
            lbl_yes.setDefaultTextColor(QColor("#000000"))
            lbl_yes.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            lbl_yes.setPos(cx + 6, d_cy + d_h / 2 + 4)
            self.scene.addItem(lbl_yes)

            # --- ГІЛКА «НІ (False)» ПРАВОРУЧ ---
            lbl_no = QGraphicsTextItem("Ні (False)")
            lbl_no.setDefaultTextColor(QColor("#000000"))
            lbl_no.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            lbl_no.setPos(cx + d_w / 2 + 8, d_cy - 24)
            self.scene.addItem(lbl_no)

            # Горизонтальна лінія без стрілки вкінці + стрілка вниз до виходу
            exit_x = cx + d_w / 2 + 110
            self.scene.addLine(cx + d_w / 2, d_cy, exit_x, d_cy, QPen(QColor("#000000"), 2))
            self._draw_arrow(exit_x, d_cy, exit_x, d_cy + 25)
            self._draw_parallelogram(exit_x - 65, d_cy + 25, 140, 40, "Вихід з циклу")

            # Опис паралелограма
            desc_exit = QGraphicsTextItem("◀ Завершення ітерацій")
            desc_exit.setDefaultTextColor(QColor("#4A5568"))
            desc_exit.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            desc_exit.setPos(exit_x + 80, d_cy + 35)
            self.scene.addItem(desc_exit)

            # Стрілка вниз від ромба -> Тіло циклу[cite: 4]
            body_y = d_cy + d_h / 2 + 35
            self._draw_arrow(cx, d_cy + d_h / 2, cx, body_y)

            # Блок 3: Тіло циклу (Поточний крок)[cite: 4]
            b3_w, b3_h = 180, 40
            b3_x = cx - b3_w / 2
            rect3 = QGraphicsRectItem(b3_x, body_y, b3_w, b3_h)
            rect3.setBrush(QBrush(QColor("#EBF8FF")))
            rect3.setPen(QPen(QColor("#3182CE"), 1.8))
            self.scene.addItem(rect3)

            t3 = QGraphicsTextItem(f"Крок: {loop_var} = {loop_val}")
            t3.setDefaultTextColor(QColor("#000000"))
            t3.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            t3.setPos(b3_x + 18, body_y + 8)
            self.scene.addItem(t3)

            # Опис блоку 3
            desc3 = QGraphicsTextItem("◀ Тіло циклу (дія на поточному кроці)")
            desc3.setDefaultTextColor(QColor("#4A5568"))
            desc3.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            desc3.setPos(b3_x + b3_w + 10, body_y + 10)
            self.scene.addItem(desc3)

            # Стрілка вниз до блоку стану[cite: 4]
            self._draw_arrow(cx, body_y + b3_h, cx, body_y + b3_h + 25)

            # Блок 4: Стан та значення[cite: 4]
            b4_y = body_y + b3_h + 25
            b4_w, b4_h = 240, 42
            b4_x = cx - b4_w / 2
            rect4 = QGraphicsRectItem(b4_x, b4_y, b4_w, b4_h)
            rect4.setBrush(QBrush(QColor("#E2E8F0")))
            rect4.setPen(QPen(QColor("#4A5568"), 1.8))
            self.scene.addItem(rect4)

            other_vars = [f"{k}={v}" for k, v in variables.items() if k != loop_var and not isinstance(v, list)]
            sub_text = ", ".join(other_vars) if other_vars else f"Ітерація {loop_val + 1} триває"
            t4 = QGraphicsTextItem(f"Стан: {sub_text}")
            t4.setDefaultTextColor(QColor("#000000"))
            t4.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            t4.setPos(b4_x + 10, b4_y + 9)
            self.scene.addItem(t4)

            # Опис блоку 4
            desc4 = QGraphicsTextItem("◀ Поточні значення змінних")
            desc4.setDefaultTextColor(QColor("#4A5568"))
            desc4.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            desc4.setPos(b4_x + b4_w + 10, b4_y + 11)
            self.scene.addItem(desc4)

            # Зворотна петля циклу (вліво, вгору та назад у ромб)[cite: 4]
            loop_left_x = cx - 150
            pen_loop = QPen(QColor("#000000"), 2)
            self.scene.addLine(cx, b4_y + b4_h, cx, b4_y + b4_h + 18, pen_loop)
            self.scene.addLine(cx, b4_y + b4_h + 18, loop_left_x, b4_y + b4_h + 18, pen_loop)
            self.scene.addLine(loop_left_x, b4_y + b4_h + 18, loop_left_x, d_cy, pen_loop)
            self._draw_arrow(loop_left_x, d_cy, cx - d_w / 2, d_cy, color="#000000", width=2)

            # Опис петлі
            desc_loop = QGraphicsTextItem("Наступна ітерація\n(повернення в умову) ▶")
            desc_loop.setDefaultTextColor(QColor("#4A5568"))
            desc_loop.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            desc_loop.setPos(loop_left_x - 145, d_cy - 12)
            self.scene.addItem(desc_loop)

        else:
            # --- РЕЖИМ 3: ЗВИЧАЙНИЙ СТЕК ЗМІННИХ[cite: 4] ---
            prev_center = None
            var_w, var_h = 140, 42
            spacing = 35

            non_list_vars = {k: v for k, v in variables.items() if not isinstance(v, list)}

            if not non_list_vars:
                empty_lbl = QGraphicsTextItem("Операції над масивом виконано.")
                empty_lbl.setDefaultTextColor(QColor("#000000"))
                empty_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
                empty_lbl.setPos(cx - empty_lbl.boundingRect().width() / 2, y + 10)
                self.scene.addItem(empty_lbl)
                return

            for name, val in non_list_vars.items():
                vx = cx - var_w / 2
                rect = QGraphicsRectItem(vx, y, var_w, var_h)
                rect.setBrush(QBrush(QColor("#BEE3F8")))
                rect.setPen(QPen(QColor("#2B6CB0"), 1.8))
                self.scene.addItem(rect)

                val_str = str(val)
                if hasattr(val, '__class__') and val.__class__.__name__ not in ('int', 'float', 'str', 'bool'):
                    val_str = f"<{val.__class__.__name__}>"

                vt = QGraphicsTextItem(f"{name} = {val_str}")
                vt.setDefaultTextColor(QColor("#000000"))
                vt.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
                vt.setPos(vx + 10, y + 10)
                self.scene.addItem(vt)

                desc = self.VARIABLE_TERMS.get(name, "Локальна змінна")
                side_lbl = QGraphicsTextItem(f"◀ {desc}")
                side_lbl.setDefaultTextColor(QColor("#4A5568"))
                side_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                side_lbl.setPos(vx + var_w + 10, y + 10)
                self.scene.addItem(side_lbl)

                if prev_center:
                    self._draw_arrow(prev_center[0], prev_center[1], vx + var_w / 2, y)

                prev_center = (vx + var_w / 2, y + var_h)
                y += var_h + spacing


# --- Поле виведення результатів консолі ---
class OutputTextEdit(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setStyleSheet("""
            background-color: #1e1e1e;
            color: #bbbbbb;
            font: 10pt Consolas;
            border-top: 1px solid #444;
        """)


# --- Головне вікно додатку ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PY.R.V.I.S.")
        self.resize(1600, 1000)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.currentChanged.connect(self.update_title_bar)

        self.output = OutputTextEdit()
        self.animation_widget = AdaptiveAnimationWidget()
        self.file_paths = {}
        self.modified_tabs = set()

        self.progress_bar = QProgressBar()
        self.status_bar = QStatusBar()
        self.status_bar.addPermanentWidget(self.progress_bar)
        self.setStatusBar(self.status_bar)

        self.fs_model = QFileSystemModel()
        self.fs_model.setRootPath(QDir.rootPath())
        self.fs_model.setNameFilters(["*.py"])
        self.fs_model.setNameFilterDisables(False)

        self.tree_view = QTreeView()
        self.tree_view.setModel(self.fs_model)
        self.tree_view.doubleClicked.connect(self.open_file_from_tree)
        self.tree_view.setHeaderHidden(True)

        self.run_button = QPushButton("▶")
        self.pause_button = QPushButton("⏸")
        self.resume_button = QPushButton("⏯")
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)

        toolbar = QToolBar("Головна панель")
        toolbar.addWidget(QLabel(" 🚀 Виконання: "))
        toolbar.addWidget(self.run_button)
        toolbar.addWidget(self.pause_button)
        toolbar.addWidget(self.resume_button)
        toolbar.addSeparator()
        self.addToolBar(toolbar)

        editor_splitter = QSplitter(Qt.Orientation.Vertical)
        editor_splitter.addWidget(self.tab_widget)
        editor_splitter.addWidget(self.output)
        editor_splitter.setSizes([750, 250])

        main_split = QSplitter(Qt.Orientation.Horizontal)
        file_dock = QDockWidget("📁 Оглядач проєкту", self)
        file_dock.setWidget(self.tree_view)
        file_dock.setMinimumWidth(220)

        main_split.addWidget(file_dock)
        main_split.addWidget(editor_splitter)
        main_split.addWidget(self.animation_widget)
        main_split.setStretchFactor(1, 3)
        main_split.setStretchFactor(2, 2)

        container = QWidget()
        container.setLayout(QVBoxLayout())
        container.layout().addWidget(main_split)
        self.setCentralWidget(container)

        self.init_menus()

        self.run_button.clicked.connect(self.run_code)
        self.pause_button.clicked.connect(self.pause_code)
        self.resume_button.clicked.connect(self.resume_code)

        self.apply_mdpu_theme()

        

    def init_menus(self):
        file_menu = self.menuBar().addMenu("📂 Файл")
        file_menu.addAction("🆕 Новий файл", self.new_tab)
        file_menu.addAction("📂 Відкрити...", self.open_file_dialog)
        file_menu.addAction("💾 Зберегти", self.save_file)
        file_menu.addAction("📝 Зберегти як...", self.save_file_as)
        file_menu.addSeparator()
        
        new_file_action = QAction("➕ Новий файл у проєкті", self)
        new_file_action.triggered.connect(self.create_new_file_in_project)
        file_menu.addAction(new_file_action)

        run_menu = self.menuBar().addMenu("▶ Запуск")
        run_menu.addAction("🚀 Запустити код", self.run_code)

        learning_menu = self.menuBar().addMenu("📚 Навчання")
        learning_menu.addAction("Вступ до Python", lambda: self.show_lesson("intro"))
        learning_menu.addAction("Змінні та типи даних", lambda: self.show_lesson("variables"))
        learning_menu.addAction("Умовні оператори", lambda: self.show_lesson("conditionals"))
        learning_menu.addAction("Цикли та лічильники", lambda: self.show_lesson("loops"))
        learning_menu.addAction("Функції", lambda: self.show_lesson("functions"))
        learning_menu.addAction("Списки та масиви", lambda: self.show_lesson("lists"))
        learning_menu.addAction("Словники (dict)", lambda: self.show_lesson("dictionaries"))
        learning_menu.addAction("Обробка винятків", lambda: self.show_lesson("exceptions"))
        learning_menu.addAction("Класи і об'єкти (ООП)", lambda: self.show_lesson("classes"))
        learning_menu.addAction("Модулі та пакети", lambda: self.show_lesson("modules"))
        learning_menu.addAction("Файли та I/O", lambda: self.show_lesson("files"))

    def apply_mdpu_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#f9fbfe"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#004085"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#e2e8f0"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#004085"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#bee3f8"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#004085"))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#f9fbfe"))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#004085"))
        self.setPalette(palette)
        self.setFont(QFont("Segoe UI", 10))

        self.setStyleSheet("""
            QMenuBar {
                background-color: #e2e8f0;
                color: #004085;
                font-weight: 500;
            }
            QMenuBar::item {
                background: transparent;
                padding: 6px 12px;
            }
            QMenuBar::item:selected {
                background: #bee3f8;
                color: #004085;
            }
            QMenu {
                background-color: #f9fbfe;
                border: 1px solid #cbd5e0;
                color: #004085;
            }
            QMenu::item:selected {
                background-color: #bee3f8;
                color: #004085;
            }
            QPushButton {
                background-color: #007bff;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
            QPushButton:pressed {
                background-color: #004085;
            }
            QPushButton:disabled {
                background-color: #a0aec0;
                color: #edf2f7;
            }
        """)

    def show_lesson(self, lesson_name):
        lesson_content = self.get_lesson_content(lesson_name)
        QMessageBox.information(self, f"Урок: {lesson_name.capitalize()}", lesson_content)

    def get_lesson_content(self, lesson_name):
        lessons = {
            "intro": "Ласкаво просимо до Python!\n\nPython — проста й потужна мова.",
            "loops": "Цикли (for / while):\n\nfor i in range(5):\n    print(f'Крок №{i}')",
            "lists": "Списки:\n\narr = [10, 20, 30]\nprint(arr[0])",
            "classes": "Класи та спадкування:\n\nclass Animal:\n    pass\n\nclass Cat(Animal):\n    pass",
        }
        return lessons.get(lesson_name, "Матеріал готується.")

    def create_new_file_in_project(self):
        if not hasattr(self, 'project_path') or not self.project_path:
            QMessageBox.warning(self, "⚠️ Немає проєкту", "Спочатку створіть або відкрийте проєкт.")
            return

    def new_tab(self, content="", filepath=None):
        editor = CodeEditor()
        editor.setFont(QFont("Consolas", 11))
        PythonHighlighter(editor.document())
        editor.setStyleSheet("background-color: #2b2b2b; color: #f0f0f0;")
        editor.textChanged.connect(self.mark_tab_as_modified)
        index = self.tab_widget.addTab(editor, "Новий файл")
        self.tab_widget.setCurrentWidget(editor)

        if filepath:
            editor.setPlainText(content)
            self.file_paths[editor] = filepath
            self.tab_widget.setTabText(index, os.path.basename(filepath))
        else:
            if content:
                editor.setPlainText(content)
            self.file_paths[editor] = None

    def current_editor(self):
        widget = self.tab_widget.currentWidget()
        if isinstance(widget, CodeEditor):
            return widget
        return None

    def mark_tab_as_modified(self):
        editor = self.current_editor()
        if editor and editor not in self.modified_tabs:
            self.modified_tabs.add(editor)
            index = self.tab_widget.indexOf(editor)
            name = self.tab_widget.tabText(index)
            if not name.endswith("*"):
                self.tab_widget.setTabText(index, name + "*")

    def update_title_bar(self):
        editor = self.current_editor()
        if editor:
            index = self.tab_widget.indexOf(editor)
            path = self.file_paths.get(editor)
            name = os.path.basename(path) if path else "Новий файл"
            if editor in self.modified_tabs:
                name += "*"
            self.tab_widget.setTabText(index, name)

    def open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Відкрити файл", "", "Python (*.py);;All Files (*)")
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self.new_tab(f.read(), path)
            except Exception as e:
                QMessageBox.critical(self, "Помилка", str(e))

    def save_file(self):
        editor = self.current_editor()
        if not editor: return
        path = self.file_paths.get(editor)
        if not path:
            return self.save_file_as()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(editor.toPlainText())
            self.modified_tabs.discard(editor)
            index = self.tab_widget.indexOf(editor)
            self.tab_widget.setTabText(index, os.path.basename(path))
        except Exception as e:
            QMessageBox.critical(self, "❌ Помилка", str(e))

    def save_file_as(self):
        editor = self.current_editor()
        if not editor: return
        path, _ = QFileDialog.getSaveFileName(self, "Зберегти як", "", "Python (*.py)")
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(editor.toPlainText())
                self.file_paths[editor] = path
                self.modified_tabs.discard(editor)
                index = self.tab_widget.indexOf(editor)
                self.tab_widget.setTabText(index, os.path.basename(path))
            except Exception as e:
                QMessageBox.critical(self, "❌ Помилка", str(e))

    def open_file_from_tree(self, index):
        path = self.fs_model.filePath(index)
        if os.path.isfile(path) and path.endswith('.py'):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self.new_tab(f.read(), path)
            except Exception as e:
                QMessageBox.critical(self, "❌ Помилка", str(e))

    def close_tab(self, index):
        editor = self.tab_widget.widget(index)
        if editor in self.modified_tabs:
            reply = QMessageBox.question(
                self,
                "Збереження змін",
                "Зберегти файл перед закриттям?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.tab_widget.setCurrentIndex(index)
                self.save_file()
            elif reply == QMessageBox.StandardButton.Cancel:
                return
        self.tab_widget.removeTab(index)
        self.file_paths.pop(editor, None)
        self.modified_tabs.discard(editor)

    def run_code(self):
        editor = self.current_editor()
        if not editor:
            return
        code = editor.toPlainText()
        self.output.clear()
        self.progress_bar.setVisible(True)
        self.run_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.resume_button.setEnabled(False)

        self.runner = CodeRunner(code, step_delay=0.45)
        self.runner.output_signal.connect(self.output.appendPlainText)
        self.runner.progress_signal.connect(self.progress_bar.setValue)
        self.runner.finished_signal.connect(self.run_finished)
        self.runner.variable_update_signal.connect(self.animation_widget.update_variables)
        self.runner.start()

    def run_finished(self):
        self.run_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)

    def pause_code(self):
        if hasattr(self, "runner"):
            self.runner.pause()
            self.pause_button.setEnabled(False)
            self.resume_button.setEnabled(True)

    def resume_code(self):
        if hasattr(self, "runner"):
            self.runner.resume()
            self.pause_button.setEnabled(True)
            self.resume_button.setEnabled(False)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())