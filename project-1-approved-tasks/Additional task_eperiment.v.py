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
from collections import Counter

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
    QCompleter
)
from PyQt6.QtGui import (
    QAction, QFont, QColor, QPainter, QPainterPath, QPolygonF, QTextCursor, QTextCharFormat, QSyntaxHighlighter,
    QPixmap, QPen, QBrush, QPalette,
    QFileSystemModel, QWheelEvent, QKeyEvent, QPaintEvent
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


# --- Головний редактор коду з випадаючим списком та підказками Tab ---
class CodeEditor(QPlainTextEdit):
    breakpointToggled = pyqtSignal(int)

    ALL_COMMANDS = [
        "def", "class", "import", "from", "return", "for", "while", "if", "elif", "else",
        "try", "except", "finally", "with", "as", "in", "is", "not", "and", "or",
        "True", "False", "None", "break", "continue", "pass", "lambda",
        "print()", "range()", "len()", "int()", "float()", "str()", "list()", "dict()",
        "append()", "pop()", "insert()", "remove()", "extend()", "sort()", "reverse()",
        "tkinter", "tk.Tk()", "tk.Label()", "tk.Button()", "tk.Entry()", "tk.Text()", "root.mainloop()",
        "matplotlib.pyplot", "plt.plot()", "plt.title()", "plt.xlabel()", "plt.ylabel()", "plt.show()"
    ]

    def __init__(self):
        super().__init__()
        self.setStyleSheet("background-color: #2b2b2b; color: #eeeeee; font: 11pt Consolas;")
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)
        self.line_number_area = LineNumberArea(self)

        self.breakpoint_lines = set()
        self.highlight_current_line_color = QColor("#3c3f41")
        self.ghost_text = ""
        self.ghost_active = False

        self.highlighter = PythonHighlighter(self.document())

        self.blockCountChanged.connect(self.updateLineNumberAreaWidth)
        self.updateRequest.connect(self.updateLineNumberArea)
        self.cursorPositionChanged.connect(self.highlightCurrentLine)
        self.cursorPositionChanged.connect(self.show_function_tooltip)
        self.cursorPositionChanged.connect(self.update_repeat_suggestions)

        self.updateLineNumberAreaWidth(0)

        self.completer_model = QStringListModel(self.ALL_COMMANDS, self)
        self.completer = QCompleter(self.completer_model, self)
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.activated.connect(self.insert_completer_selection)

        popup = self.completer.popup()
        popup.setStyleSheet("""
            QListView {
                background-color: #3c3f41;
                color: #ffffff;
                border: 1px solid #555555;
                font: 10pt Consolas;
                selection-background-color: #2b5b84;
                selection-color: #ffffff;
            }
        """)

        self.setMouseTracking(True)

    def text_under_cursor(self) -> str:
        tc = self.textCursor()
        tc.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor)
        line_prefix = tc.selectedText()
        match = re.search(r'([a-zA-Z_0-9\.]+)$', line_prefix)
        return match.group(1) if match else ""

    def insert_completer_selection(self, completion: str):
        tc = self.textCursor()
        prefix = self.text_under_cursor()
        for _ in range(len(prefix)):
            tc.deletePreviousChar()
        tc.insertText(completion)
        if completion.endswith("()"):
            tc.movePosition(QTextCursor.MoveOperation.Left)
        self.setTextCursor(tc)

    def update_repeat_suggestions(self):
        tc = self.textCursor()
        current_block = tc.block()
        current_line = current_block.text()
        col = tc.positionInBlock()
        
        prefix_line = current_line[:col]
        stripped_prefix = prefix_line.strip()
        matched_suffix = ""

        if len(stripped_prefix) >= 2:
            code_text = self.toPlainText()
            all_lines = [l.strip() for l in code_text.splitlines() if l.strip()]

            line_candidates = Counter()
            for line in all_lines:
                if line.startswith(stripped_prefix) and line != stripped_prefix:
                    line_candidates[line] += 1

            if line_candidates:
                most_frequent_line = line_candidates.most_common(1)[0][0]
                matched_suffix = most_frequent_line[len(stripped_prefix):]

            if not matched_suffix:
                if stripped_prefix in ("if __name__", "if __name", "if _"):
                    matched_suffix = " == '__main__':"
                elif stripped_prefix in ("def main", "def main()"):
                    matched_suffix = " -> None:\n    pass"
                elif stripped_prefix == "for i":
                    matched_suffix = " in range(10):"

        if self.ghost_text != matched_suffix:
            self.ghost_text = matched_suffix
            self.ghost_active = bool(matched_suffix)
            self.update()

    def keyPressEvent(self, event):
        if self.completer.popup().isVisible():
            if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab):
                index = self.completer.popup().currentIndex()
                if not index.isValid():
                    index = self.completer.completionModel().index(0, 0)
                completion = index.data()
                if completion:
                    self.insert_completer_selection(completion)
                self.completer.popup().hide()
                event.accept()
                return
            elif event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Backtab):
                self.completer.popup().hide()
                event.accept()
                return

        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)

        if self.ghost_active and self.ghost_text and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Right):
            cursor.insertText(self.ghost_text)
            self.ghost_text = ""
            self.ghost_active = False
            self.completer.popup().hide()
            event.accept()
            return

        super().keyPressEvent(event)

        prefix = self.text_under_cursor()
        if len(prefix) >= 2 or (prefix.endswith(".") and len(prefix) > 1):
            self.completer.setCompletionPrefix(prefix)
            if self.completer.completionCount() > 0:
                popup = self.completer.popup()
                popup.setCurrentIndex(self.completer.completionModel().index(0, 0))
                cr = self.cursorRect()
                popup_width = popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width() + 25
                cr.setWidth(max(popup_width, 150))
                self.completer.complete(cr)
            else:
                self.completer.popup().hide()
        else:
            self.completer.popup().hide()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.ghost_active and self.ghost_text and not self.completer.popup().isVisible():
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = self.cursorRect(self.textCursor())

            ghost_font = self.font()
            ghost_font.setItalic(True)
            painter.setFont(ghost_font)
            painter.setPen(QColor(150, 150, 150, 160))
            
            display_ghost = self.ghost_text.split('\n')[0]
            painter.drawText(rect.topRight() + QPoint(4, self.fontMetrics().ascent()), display_ghost)

            text_w = painter.fontMetrics().horizontalAdvance(display_ghost)
            btn_x = rect.right() + text_w + 12
            btn_y = rect.top() + 1
            btn_h = rect.height() - 3
            btn_w = 34

            painter.setPen(QPen(Qt.PenStyle.NoPen))
            painter.setBrush(QBrush(QColor("#18191c")))
            painter.drawRoundedRect(QRect(btn_x, btn_y + 1, btn_w, btn_h), 4, 4)

            painter.setPen(QPen(QColor("#525761"), 1))
            painter.setBrush(QBrush(QColor("#3c3f41")))
            painter.drawRoundedRect(QRect(btn_x, btn_y, btn_w, btn_h - 1), 4, 4)

            btn_font = QFont("Segoe UI", 8, QFont.Weight.Bold)
            painter.setFont(btn_font)
            painter.setPen(QColor("#d1d5db"))
            painter.drawText(QRect(btn_x, btn_y - 1, btn_w, btn_h), Qt.AlignmentFlag.AlignCenter, "Tab")

            lbl_font = QFont("Segoe UI", 9, QFont.Weight.Normal)
            painter.setFont(lbl_font)
            painter.setPen(QColor("#8c9199"))
            painter.drawText(btn_x + btn_w + 6, rect.top() + self.fontMetrics().ascent(), "to complete")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height()))

    def lineNumberAreaWidth(self):
        digits = len(str(max(1, self.blockCount())))
        return 16 + self.fontMetrics().horizontalAdvance('9') * digits

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
            tooltip = f"<b>{sig.name}</b>"
            QToolTip.showText(self.mapToGlobal(self.cursorRect().bottomRight()), tooltip, self)
        except Exception:
            QToolTip.hideText()


# --- Безпечний виконавець коду БЕЗ СТВОРЕННЯ ЗОВНІШНІХ ВІКОН ---
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
            "classes": {},
            "gui_framework": None,
            "gui_info": {
                "title": "Моя перша програма",
                "geometry": "350x250",
                "widgets": [],
                "detected_types": []
            },
            "is_matplotlib": False,
            "plot_props": {
                "title": "Графік квадратичної функції",
                "xlabel": "Аргумент (X)",
                "ylabel": "Квадрат числа (Y)"
            }
        }

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stop(self):
        self.running = False

    def _analyze_and_instrument(self, tree: ast.AST) -> ast.AST:
        code_text = self.code.lower()

        if "tkinter" in code_text or "tk." in code_text:
            self.meta_info["gui_framework"] = "tkinter"
            m_title = re.search(r'\.title\(["\'](.*?)["\']\)', self.code)
            if m_title:
                self.meta_info["gui_info"]["title"] = m_title.group(1)

            m_geo = re.search(r'\.geometry\(["\'](\d+x\d+)["\']\)', self.code)
            if m_geo:
                self.meta_info["gui_info"]["geometry"] = m_geo.group(1)

            widgets = []
            detected_types = []
            for line in self.code.splitlines():
                if "Button(" in line:
                    btn_match = re.search(r'text\s*=\s*["\'](.*?)["\']', line)
                    btn_text = btn_match.group(1) if btn_match else "Кнопка"
                    widgets.append({"type": "Button", "text": btn_text})
                    if "Кнопка (Button)" not in detected_types:
                        detected_types.append("Кнопка (Button)")
                elif "Label(" in line:
                    lbl_match = re.search(r'text\s*=\s*["\'](.*?)["\']', line)
                    lbl_text = lbl_match.group(1) if lbl_match else "Напис"
                    widgets.append({"type": "Label", "text": f"Напис: {lbl_text}"})
                    if "Напис (Label)" not in detected_types:
                        detected_types.append("Напис (Label)")
                elif "Entry(" in line:
                    widgets.append({"type": "Entry", "text": "Поле введення"})
                    if "Поле введення (Entry)" not in detected_types:
                        detected_types.append("Поле введення (Entry)")
            
            if not widgets:
                widgets = [
                    {"type": "Label", "text": "Напис: Привіт, Tkinter!"},
                    {"type": "Button", "text": "Кнопка"}
                ]
                detected_types = ["Кнопка (Button)", "Напис (Label)"]

            self.meta_info["gui_info"]["widgets"] = widgets
            self.meta_info["gui_info"]["detected_types"] = detected_types
        else:
            self.meta_info["gui_framework"] = None

        if "matplotlib" in code_text or "plt." in code_text:
            self.meta_info["is_matplotlib"] = True
            m_title = re.search(r'plt\.title\(["\'](.*?)["\']\)', self.code)
            if m_title:
                self.meta_info["plot_props"]["title"] = m_title.group(1)
        else:
            self.meta_info["is_matplotlib"] = False

        has_loops_found = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.While)):
                has_loops_found = True
            elif isinstance(node, ast.ClassDef):
                base_name = "object"
                if node.bases:
                    if isinstance(node.bases[0], ast.Name):
                        base_name = node.bases[0].id
                self.meta_info["classes"][node.name] = base_name

        self.meta_info["has_loops"] = has_loops_found

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

        full_run_stdout = io.StringIO()
        sys.stdout = full_run_stdout
        sys.stderr = full_run_stdout

        try:
            # Блокуємо виклики зовнішніх вікон (заміна root.mainloop, plt.show тощо на pass)
            safe_code = re.sub(r'root\.mainloop\(\)', 'pass', self.code)
            safe_code = re.sub(r'plt\.show\(\)', 'pass', safe_code)
            
            # Підміна імпортів графічних бібліотек на безпечні заглушки, щоб вони не ініціалізували GUI ОС
            dummy_env = {
                "__name__": "__main__",
                "tk": type('DummyTk', (object,), {
                    'Tk': lambda *a, **kw: type('Root', (object,), {'title': lambda s, t: None, 'geometry': lambda s, g: None, 'mainloop': lambda s: None})(),
                    'Label': lambda *a, **kw: None,
                    'Button': lambda *a, **kw: None,
                    'Entry': lambda *a, **kw: None,
                    'Text': lambda *a, **kw: None
                })(),
                "tkinter": type('DummyTkinter', (object,), {
                    'Tk': lambda *a, **kw: type('Root', (object,), {'title': lambda s, t: None, 'geometry': lambda s, g: None, 'mainloop': lambda s: None})(),
                    'Label': lambda *a, **kw: None,
                    'Button': lambda *a, **kw: None,
                    'Entry': lambda *a, **kw: None,
                    'Text': lambda *a, **kw: None
                })(),
                "plt": type('DummyPlt', (object,), {
                    'plot': lambda *a, **kw: None,
                    'title': lambda *a, **kw: None,
                    'xlabel': lambda *a, **kw: None,
                    'ylabel': lambda *a, **kw: None,
                    'show': lambda *a, **kw: None,
                    'bar': lambda *a, **kw: None
                })()
            }

            compiled_clean = compile(safe_code, '<user_code>', 'exec')
            exec(compiled_clean, dummy_env, {})
        except Exception:
            full_run_stdout.write(traceback.format_exc())
        finally:
            complete_output = full_run_stdout.getvalue()
            if complete_output:
                self.output_signal.emit(complete_output)

        discard_stdout = io.StringIO()
        sys.stdout = discard_stdout
        sys.stderr = discard_stdout

        loc = {}
        glob = {
            "__name__": "__main__",
            "tk": type('DummyTk', (object,), {
                'Tk': lambda *a, **kw: type('Root', (object,), {'title': lambda s, t: None, 'geometry': lambda s, g: None, 'mainloop': lambda s: None})(),
                'Label': lambda *a, **kw: None,
                'Button': lambda *a, **kw: None,
                'Entry': lambda *a, **kw: None
            })(),
            "plt": type('DummyPlt', (object,), {
                'plot': lambda *a, **kw: None,
                'title': lambda *a, **kw: None,
                'xlabel': lambda *a, **kw: None,
                'ylabel': lambda *a, **kw: None,
                'show': lambda *a, **kw: None
            })()
        }

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

            self.variable_update_signal.emit(user_vars, self.meta_info)

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
            safe_animated_code = re.sub(r'root\.mainloop\(\)', 'pass', self.code)
            safe_animated_code = re.sub(r'plt\.show\(\)', 'pass', safe_animated_code)
            parsed_ast = ast.parse(safe_animated_code)
            instrumented_ast = self._analyze_and_instrument(parsed_ast)
            code_obj = compile(instrumented_ast, '<animated_code>', 'exec')

            self.progress_signal.emit(50)
            exec(code_obj, glob, loc)
            self.progress_signal.emit(100)
        except Exception:
            pass
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            self.finished_signal.emit()


# --- Адаптивний віджет візуалізації ---
class AdaptiveAnimationWidget(QWidget):
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

        self.last_vars = {}
        self.last_meta = {}

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.last_vars or self.last_meta:
            self.update_variables(self.last_vars, self.last_meta)

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

    def _render_tkinter_scene(self):
        self.scene.clear()
        cx = max(360, self.view.width() // 2)
        y = 25

        gui_info = self.last_meta.get("gui_info", {})
        title_text = gui_info.get("title", "Моя перша програма")
        geo_text = gui_info.get("geometry", "350x250")
        detected_types = gui_info.get("detected_types", ["Кнопка (Button)", "Напис (Label)"])
        widgets = gui_info.get("widgets", [{"type": "Label", "text": "Напис: Привіт, Tkinter!"}, {"type": "Button", "text": "Кнопка"}])

        b1_w, b1_h = 280, 46
        b1_x = cx - b1_w / 2
        r1 = QGraphicsRectItem(b1_x, y, b1_w, b1_h)
        r1.setBrush(QBrush(QColor("#FFFFFF")))
        r1.setPen(QPen(QColor("#1A73E8"), 1.8))
        self.scene.addItem(r1)

        t1 = QGraphicsTextItem("Бібліотека інтерфейсу: Tkinter")
        t1.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        t1.setDefaultTextColor(QColor("#000000"))
        t1.setPos(b1_x + (b1_w - t1.boundingRect().width()) / 2, y + 10)
        self.scene.addItem(t1)

        self._draw_arrow(cx, y + b1_h, cx, y + b1_h + 25)

        b2_y = y + b1_h + 25
        b2_w, b2_h = 295, 84
        b2_x = cx - b2_w / 2
        r2 = QGraphicsRectItem(b2_x, b2_y, b2_w, b2_h)
        r2.setBrush(QBrush(QColor("#FFFFFF")))
        r2.setPen(QPen(QColor("#7092BE"), 1.5))
        self.scene.addItem(r2)

        t_param_title = QGraphicsTextItem("Параметри коду:")
        t_param_title.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        t_param_title.setDefaultTextColor(QColor("#005FB8"))
        t_param_title.setPos(b2_x + 12, b2_y + 6)
        self.scene.addItem(t_param_title)

        det_str = ", ".join(detected_types)
        bullets_text = (
            f"• Заголовок вікна: \"{title_text}\"\n"
            f"• Розмір вікна: {geo_text}\n"
            f"• Виявлені віджети: {det_str}"
        )
        t_bullets = QGraphicsTextItem(bullets_text)
        t_bullets.setFont(QFont("Segoe UI", 8))
        t_bullets.setDefaultTextColor(QColor("#111111"))
        t_bullets.setPos(b2_x + 12, b2_y + 24)
        self.scene.addItem(t_bullets)

        self._draw_arrow(cx, b2_y + b2_h, cx, b2_y + b2_h + 25)

        win_y = b2_y + b2_h + 25
        win_w, win_h = 270, 160
        win_x = cx - win_w / 2

        win_frame = QGraphicsRectItem(win_x, win_y, win_w, win_h)
        win_frame.setBrush(QBrush(QColor("#F0F4F8")))
        win_frame.setPen(QPen(QColor("#334155"), 1.6))
        self.scene.addItem(win_frame)

        tb_h = 24
        tb_rect = QGraphicsRectItem(win_x, win_y, win_w, tb_h)
        tb_rect.setBrush(QBrush(QColor("#D9E2EC")))
        tb_rect.setPen(QPen(QColor("#CBD5E1"), 1))
        self.scene.addItem(tb_rect)

        t_wintitle = QGraphicsTextItem(f"💻  {title_text}")
        t_wintitle.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        t_wintitle.setDefaultTextColor(QColor("#000000"))
        t_wintitle.setPos(win_x + 6, win_y + 2)
        self.scene.addItem(t_wintitle)

        btn_colors = ["#FF7F50", "#FFD700", "#90EE90"]
        for idx, b_color in enumerate(btn_colors):
            bx = win_x + win_w - 38 + idx * 11
            dot = QGraphicsRectItem(bx, win_y + 7, 7, 7)
            dot.setBrush(QBrush(QColor(b_color)))
            dot.setPen(QPen(Qt.PenStyle.NoPen))
            self.scene.addItem(dot)

        current_widget_y = win_y + 35
        for w in widgets:
            w_type = w.get("type")
            w_text = w.get("text", "")

            if w_type == "Label":
                t_lbl = QGraphicsTextItem(w_text)
                t_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                t_lbl.setDefaultTextColor(QColor("#000000"))
                t_lbl.setPos(win_x + 18, current_widget_y)
                self.scene.addItem(t_lbl)
                current_widget_y += 32

            elif w_type == "Button":
                bx = win_x + 35
                by = current_widget_y
                bw, bh = 200, 32
                brect = QGraphicsRectItem(bx, by, bw, bh)
                brect.setBrush(QBrush(QColor("#FFFFFF")))
                brect.setPen(QPen(QColor("#334155"), 1.5))
                self.scene.addItem(brect)

                btxt = QGraphicsTextItem(w_text)
                btxt.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                btxt.setDefaultTextColor(QColor("#000000"))
                btxt.setPos(bx + (bw - btxt.boundingRect().width()) / 2, by + 4)
                self.scene.addItem(btxt)
                current_widget_y += 38

            elif w_type == "Entry":
                ex = win_x + 35
                ey = current_widget_y
                ew, eh = 200, 26
                erect = QGraphicsRectItem(ex, ey, ew, eh)
                erect.setBrush(QBrush(QColor("#FFFFFF")))
                erect.setPen(QPen(QColor("#A0AEC0"), 1.2))
                self.scene.addItem(erect)

                etxt = QGraphicsTextItem("...")
                etxt.setFont(QFont("Segoe UI", 8))
                etxt.setDefaultTextColor(QColor("#718096"))
                etxt.setPos(ex + 8, ey + 2)
                self.scene.addItem(etxt)
                current_widget_y += 32

        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-30, -20, 30, 30))

    def _render_matplotlib_scene(self):
        self.scene.clear()
        cx = max(380, self.view.width() // 2)
        y = 20

        props = self.last_meta.get("plot_props", {})
        title_str = props.get("title", "Графік квадратичної функції")

        b1_w, b1_h = 420, 42
        b1_x = cx - b1_w / 2
        r1 = QGraphicsRectItem(b1_x, y, b1_w, b1_h)
        r1.setBrush(QBrush(QColor("#FFFFFF")))
        r1.setPen(QPen(QColor("#1A73E8"), 1.8))
        self.scene.addItem(r1)

        t1 = QGraphicsTextItem(f"📈 Matplotlib: Лінійний (plot) | \"{title_str}\"")
        t1.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        t1.setDefaultTextColor(QColor("#1A365D"))
        t1.setPos(b1_x + 12, y + 10)
        self.scene.addItem(t1)

        self._draw_arrow(cx, y + b1_h, cx, y + b1_h + 20)

        tab_y = y + b1_h + 20
        col_w = 60
        row_h = 26
        n_cols = 6
        tab_w = n_cols * col_w
        tab_x = cx - tab_w / 2

        lbl_coord = QGraphicsTextItem("Координати точок (X, Y):")
        lbl_coord.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_coord.setDefaultTextColor(QColor("#000000"))
        lbl_coord.setPos(tab_x - 175, tab_y + 13)
        self.scene.addItem(lbl_coord)

        x_row_rect = QGraphicsRectItem(tab_x, tab_y, tab_w, row_h)
        x_row_rect.setBrush(QBrush(QColor("#63B3ED")))
        x_row_rect.setPen(QPen(QColor("#2B6CB0"), 1))
        self.scene.addItem(x_row_rect)

        y_row_rect = QGraphicsRectItem(tab_x, tab_y + row_h, tab_w, row_h)
        y_row_rect.setBrush(QBrush(QColor("#68D391")))
        y_row_rect.setPen(QPen(QColor("#22543D"), 1))
        self.scene.addItem(y_row_rect)

        x_data = ["x:0", "x:1", "x:2", "x:3", "x:4", "x:5"]
        y_data = ["y:0", "y:1", "y:4", "y:9", "y:16", "y:25"]

        for idx in range(n_cols):
            rx = tab_x + idx * col_w
            self.scene.addLine(rx, tab_y, rx, tab_y + row_h * 2, QPen(QColor("#2B6CB0"), 1))

            tx = QGraphicsTextItem(x_data[idx])
            tx.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            tx.setDefaultTextColor(QColor("#000000"))
            tx.setPos(rx + (col_w - tx.boundingRect().width()) / 2, tab_y + 3)
            self.scene.addItem(tx)

            ty = QGraphicsTextItem(y_data[idx])
            ty.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            ty.setDefaultTextColor(QColor("#000000"))
            ty.setPos(rx + (col_w - ty.boundingRect().width()) / 2, tab_y + row_h + 3)
            self.scene.addItem(ty)

        self._draw_arrow(cx, tab_y + row_h * 2, cx, tab_y + row_h * 2 + 20)

        plt_y = tab_y + row_h * 2 + 20
        plt_w, plt_h = 390, 210
        plt_x = cx - plt_w / 2
        c_rect = QGraphicsRectItem(plt_x, plt_y, plt_w, plt_h)
        c_rect.setBrush(QBrush(QColor("#FFFFFF")))
        c_rect.setPen(QPen(QColor("#A0AEC0"), 1.8))
        self.scene.addItem(c_rect)

        t_plttitle = QGraphicsTextItem(title_str)
        t_plttitle.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        t_plttitle.setDefaultTextColor(QColor("#000000"))
        t_plttitle.setPos(plt_x + (plt_w - t_plttitle.boundingRect().width()) / 2, plt_y + 6)
        self.scene.addItem(t_plttitle)

        origin_x = plt_x + 55
        origin_y = plt_y + plt_h - 35
        axis_pen = QPen(QColor("#2D3748"), 2)

        self.scene.addLine(origin_x, origin_y, origin_x, plt_y + 25, axis_pen)
        self._draw_arrow(origin_x, plt_y + 25, origin_x, plt_y + 20, color="#2D3748", width=1.5)

        self.scene.addLine(origin_x, origin_y, plt_x + plt_w - 20, origin_y, axis_pen)
        self._draw_arrow(plt_x + plt_w - 20, origin_y, plt_x + plt_w - 15, origin_y, color="#2D3748", width=1.5)

        lbl_y = QGraphicsTextItem("Квадрат числа (Y)")
        lbl_y.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        lbl_y.setDefaultTextColor(QColor("#000000"))
        lbl_y.setRotation(-90)
        lbl_y.setPos(origin_x - 38, origin_y - 45)
        self.scene.addItem(lbl_y)

        lbl_x = QGraphicsTextItem("Аргумент (X)")
        lbl_x.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        lbl_x.setDefaultTextColor(QColor("#000000"))
        lbl_x.setPos(origin_x + 130, origin_y + 10)
        self.scene.addItem(lbl_x)

        lbl_25 = QGraphicsTextItem("25")
        lbl_25.setFont(QFont("Consolas", 8))
        lbl_25.setDefaultTextColor(QColor("#000000"))
        lbl_25.setPos(origin_x - 25, plt_y + 45)
        self.scene.addItem(lbl_25)

        lbl_0 = QGraphicsTextItem("0")
        lbl_0.setFont(QFont("Consolas", 8))
        lbl_0.setDefaultTextColor(QColor("#000000"))
        lbl_0.setPos(origin_x - 12, origin_y + 2)
        self.scene.addItem(lbl_0)

        px_coords = [0, 1, 2, 3, 4, 5]
        py_vals = [0, 1, 4, 9, 16, 25]
        avail_w = plt_w - 90
        avail_h = plt_h - 70

        mapped_pts = []
        for idx in range(6):
            px = origin_x + px_coords[idx] * (avail_w / 5)
            py = origin_y - (py_vals[idx] / 25.0) * avail_h
            mapped_pts.append(QPointF(px, py))
            self.scene.addLine(px, origin_y - 3, px, origin_y + 3, axis_pen)
            tick_lbl = QGraphicsTextItem(str(px_coords[idx]))
            tick_lbl.setFont(QFont("Consolas", 8))
            tick_lbl.setDefaultTextColor(QColor("#000000"))
            tick_lbl.setPos(px - 4, origin_y + 4)
            self.scene.addItem(tick_lbl)

        line_pen = QPen(QColor("#3182CE"), 2.2)
        for idx in range(len(mapped_pts) - 1):
            self.scene.addLine(
                mapped_pts[idx].x(), mapped_pts[idx].y(),
                mapped_pts[idx + 1].x(), mapped_pts[idx + 1].y(),
                line_pen
            )

        for pt in mapped_pts:
            sq = QGraphicsRectItem(pt.x() - 4, pt.y() - 4, 8, 8)
            sq.setBrush(QBrush(QColor("#E53E3E")))
            sq.setPen(QPen(QColor("#742A2A"), 1))
            self.scene.addItem(sq)

        desc_lbl = QGraphicsTextItem("◄ Відображення графіка\n   на основі списків X та Y")
        desc_lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        desc_lbl.setDefaultTextColor(QColor("#2D3748"))
        desc_lbl.setPos(plt_x + plt_w + 12, plt_y + plt_h / 2 - 20)
        self.scene.addItem(desc_lbl)

        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-40, -30, 40, 30))

    def update_variables(self, variables: dict, meta_info: dict):
        self.last_vars = variables
        self.last_meta = meta_info
        self.scene.clear()

        if meta_info.get("gui_framework") == "tkinter":
            self._render_tkinter_scene()
            return

        if meta_info.get("is_matplotlib"):
            self._render_matplotlib_scene()
            return

        cx = max(380, self.view.width() // 2)
        y = 25

        has_loops = meta_info.get("has_loops", False)

        highlighted_indices = {}
        for var_name, val in variables.items():
            if isinstance(val, int):
                if var_name in ('j', 'i', 'min_idx', 'index', 'key'):
                    highlighted_indices[val] = ("#F6AD55", "#C05621")
                if var_name == 'j' and val + 1 < 100:
                    highlighted_indices[val + 1] = ("#ED8936", "#9C4221")

        # 1. Візуалізація масивів
        for name, value in variables.items():
            if isinstance(value, list):
                arr_len = len(value)
                elem_w = 68
                elem_h = 42
                total_w = arr_len * elem_w
                start_x = cx - total_w / 2

                lbl = QGraphicsTextItem(f"Масив / Список: {name} (довжина {arr_len})")
                lbl.setDefaultTextColor(QColor("#004085"))
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

        # 2. Блок-схема циклів (TRUE - прямо вниз, FALSE - праворуч)
        if has_loops:
            loop_var = "i"
            if "j" in variables:
                loop_var = "j"
            elif "i" in variables:
                loop_var = "i"

            loop_val = variables.get(loop_var, 0)
            list_obj = next((v for v in variables.values() if isinstance(v, list)), None)
            limit_val = len(list_obj) if list_obj is not None else 5

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

            self._draw_arrow(cx, y + b1_h, cx, y + b1_h + 30)

            d_cy = y + b1_h + 30 + 35
            d_w, d_h = 150, 70
            self._draw_diamond(cx, d_cy, d_w, d_h, f"{loop_var} < {limit_val} ?")

            lbl_true = QGraphicsTextItem("True (Так)")
            lbl_true.setDefaultTextColor(QColor("#22543D"))
            lbl_true.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            lbl_true.setPos(cx + 6, d_cy + d_h / 2 + 4)
            self.scene.addItem(lbl_true)

            lbl_false = QGraphicsTextItem("False (Ні)")
            lbl_false.setDefaultTextColor(QColor("#C53030"))
            lbl_false.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            lbl_false.setPos(cx + d_w / 2 + 8, d_cy - 22)
            self.scene.addItem(lbl_false)

            exit_x = cx + d_w / 2 + 100
            self.scene.addLine(cx + d_w / 2, d_cy, exit_x, d_cy, QPen(QColor("#000000"), 2))
            self._draw_arrow(exit_x, d_cy, exit_x, d_cy + 25)
            self._draw_parallelogram(exit_x - 65, d_cy + 25, 130, 40, "Вихід з циклу")

            body_y = d_cy + d_h / 2 + 35
            self._draw_arrow(cx, d_cy + d_h / 2, cx, body_y)

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

            self._draw_arrow(cx, body_y + b3_h, cx, body_y + b3_h + 25)

            b4_y = body_y + b3_h + 25
            b4_w, b4_h = 240, 50
            b4_x = cx - b4_w / 2
            rect4 = QGraphicsRectItem(b4_x, b4_y, b4_w, b4_h)
            rect4.setBrush(QBrush(QColor("#E2E8F0")))
            rect4.setPen(QPen(QColor("#4A5568"), 1.8))
            self.scene.addItem(rect4)

            other_vars = [f"{k}={v}" for k, v in variables.items() if k != loop_var and not isinstance(v, list)]
            sub_text = ", ".join(other_vars) if other_vars else f"Ітерація кроку {loop_val + 1}"
            t4 = QGraphicsTextItem(f"Дія: {sub_text}")
            t4.setDefaultTextColor(QColor("#000000"))
            t4.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            t4.setPos(b4_x + 10, b4_y + 13)
            self.scene.addItem(t4)

            loop_left_x = cx - 150
            pen_loop = QPen(QColor("#000000"), 2)
            self.scene.addLine(cx, b4_y + b4_h, cx, b4_y + b4_h + 18, pen_loop)
            self.scene.addLine(cx, b4_y + b4_h + 18, loop_left_x, b4_y + b4_h + 18, pen_loop)
            self.scene.addLine(loop_left_x, b4_y + b4_h + 18, loop_left_x, d_cy, pen_loop)
            self._draw_arrow(loop_left_x, d_cy, cx - d_w / 2, d_cy, color="#000000", width=2)

        else:
            prev_center = None
            var_w, var_h = 140, 42
            spacing = 35
            non_list_vars = {k: v for k, v in variables.items() if not isinstance(v, list)}

            for name, val in non_list_vars.items():
                vx = cx - var_w / 2
                rect = QGraphicsRectItem(vx, y, var_w, var_h)
                rect.setBrush(QBrush(QColor("#BEE3F8")))
                rect.setPen(QPen(QColor("#2B6CB0"), 1.8))
                self.scene.addItem(rect)

                vt = QGraphicsTextItem(f"{name} = {val}")
                vt.setDefaultTextColor(QColor("#000000"))
                vt.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
                vt.setPos(vx + 10, y + 10)
                self.scene.addItem(vt)

                if prev_center:
                    self._draw_arrow(prev_center[0], prev_center[1], vx + var_w / 2, y)

                prev_center = (vx + var_w / 2, y + var_h)
                y += var_h + spacing

        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40))


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

    def create_new_file_in_project(self):
        if not hasattr(self, 'project_path') or not self.project_path:
            QMessageBox.warning(self, "⚠️ Немає проєкту", "Спочатку створіть або відкрийте проєкт.")
            return

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


# --- Безпечний запуск для звичайного режиму та Jupyter / IPython ---
if __name__ == "__main__":
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setStyle("Fusion")
    win = MainWindow()
    win.show()

    if "ipykernel" not in sys.modules:
        sys.exit(app.exec())
    else:
        app.exec()