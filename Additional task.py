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
import queue
import threading
import subprocess

# --- Налаштування контексту до створення QApplication ---
from PyQt6.QtCore import Qt, QCoreApplication
try:
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
except Exception:
    pass

# --- PyQt6 ---
from PyQt6.QtWidgets import (
    QApplication, QGraphicsPolygonItem, QGraphicsRectItem, QGraphicsTextItem,
    QMainWindow, QStatusBar, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QToolTip,
    QPlainTextEdit, QListView, QGraphicsView, QGraphicsScene,
    QSplitter, QTabWidget, QToolBar, QLabel, QTextEdit, QLineEdit,
    QInputDialog, QFileDialog, QMessageBox, QProgressBar, QDockWidget, QTreeView,
    QGraphicsObject, QDialog, QCheckBox, QGroupBox, QFormLayout, QFrame, QComboBox, QStackedWidget
)
from PyQt6.QtGui import (
    QAction, QFont, QColor, QPainter, QPainterPath, QPolygonF, QTextCursor, QTextCharFormat, QSyntaxHighlighter,
    QPixmap, QPen, QBrush, QPalette,
    QFileSystemModel, QWheelEvent, QKeyEvent, QIcon
)
from PyQt6.QtCore import (
    QTimer, QSize, QRect, QRectF, QPoint, QPointF, QDir, QUrl, pyqtSignal,
    QThread, QRegularExpression, QStringListModel,
    QPropertyAnimation, QParallelAnimationGroup, QSequentialAnimationGroup, QEasingCurve
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


# --- Потоковий виконавець коду з інтерактивним введенням та перехопленням відсутніх бібліотек ---
class CodeRunner(QThread):
    output_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal()
    variable_update_signal = pyqtSignal(dict, dict)
    input_requested_signal = pyqtSignal(str)
    missing_library_signal = pyqtSignal(str)

    def __init__(self, code, project_dir=None, step_delay=0.45):
        super().__init__()
        self.code = code
        self.project_dir = project_dir
        self.step_delay = step_delay
        self.running = True
        self.paused = False

        self.input_queue = queue.Queue()
        self.waiting_for_input = False

        self.meta_info = {
            "has_loops": False,
            "loops": [],
            "has_conditionals": False,
            "conditionals": [],
            "classes": {},
            "class_details": {},
            "relations": [],
            "file_ops": {
                "has_files": False,
                "input_file": None,
                "output_file": None,
                "file_code_lines": [],
                "code_file_content": []
            }
        }

    def provide_input(self, text: str):
        self.input_queue.put(text)

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stop(self):
        self.running = False
        self.input_queue.put("")

    def _analyze_and_instrument(self, tree: ast.AST) -> ast.AST:
        class_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        known_classes = {c.name for c in class_nodes}
        code_lines = self.code.splitlines()

        # 0. Визначення головної керівної структури (для пріоритету відображення блок-схеми)
        primary = None
        for stmt in tree.body:
            if isinstance(stmt, ast.ClassDef):
                primary = "classes"
                break
            elif isinstance(stmt, (ast.For, ast.While)):
                primary = "loop"
                break
            elif isinstance(stmt, ast.If):
                primary = "conditional"
                break

        if not primary:
            for n in ast.walk(tree):
                if isinstance(n, ast.ClassDef):
                    primary = "classes"
                    break
                elif isinstance(n, (ast.For, ast.While)):
                    primary = "loop"
                    break
                elif isinstance(n, ast.If):
                    primary = "conditional"
                    break

        self.meta_info["primary_structure"] = primary

        for node in ast.walk(tree):
            if isinstance(node, ast.While):
                self.meta_info["has_loops"] = True
                test_str = ast.unparse(node.test) if hasattr(ast, "unparse") else "cond"
                body_strs = [ast.unparse(s) for s in node.body] if hasattr(ast, "unparse") else [str(s) for s in node.body]
                orelse_strs = [ast.unparse(s) for s in node.orelse] if node.orelse and hasattr(ast, "unparse") else []

                is_while_true = test_str.strip() in ("True", "1", "True == True")
                has_break = any(isinstance(n, ast.Break) for n in ast.walk(node))
                has_continue = any(isinstance(n, ast.Continue) for n in ast.walk(node))

                break_cond = None
                continue_cond = None
                for sub_if in [n for n in ast.walk(node) if isinstance(n, ast.If)]:
                    if any(isinstance(b, ast.Break) for b in sub_if.body):
                        break_cond = ast.unparse(sub_if.test) if hasattr(ast, "unparse") else "break_cond"
                    if any(isinstance(c, ast.Continue) for c in sub_if.body):
                        continue_cond = ast.unparse(sub_if.test) if hasattr(ast, "unparse") else "continue_cond"

                # Визначення змінної циклу з виразу умови
                test_vars = [n.id for n in ast.walk(node.test) if isinstance(n, ast.Name) and n.id not in ("True", "False", "None", "len", "range", "int", "float", "str")]
                target_var = test_vars[0] if test_vars else "i"

                self.meta_info["loops"].append({
                    "type": "while",
                    "test": test_str,
                    "target": target_var,
                    "test_vars": test_vars,
                    "body": body_strs,
                    "orelse": orelse_strs,
                    "is_while_true": is_while_true,
                    "has_break": has_break,
                    "has_continue": has_continue,
                    "break_cond": break_cond,
                    "continue_cond": continue_cond
                })
            elif isinstance(node, ast.For):
                self.meta_info["has_loops"] = True
                target_str = ast.unparse(node.target) if hasattr(ast, "unparse") else "var"
                iter_str = ast.unparse(node.iter) if hasattr(ast, "unparse") else "seq"
                body_strs = [ast.unparse(s) for s in node.body] if hasattr(ast, "unparse") else [str(s) for s in node.body]
                orelse_strs = [ast.unparse(s) for s in node.orelse] if node.orelse and hasattr(ast, "unparse") else []

                is_range = False
                range_args = []
                if isinstance(node.iter, ast.Call) and getattr(node.iter.func, 'id', '') == 'range':
                    is_range = True
                    range_args = [ast.unparse(a) if hasattr(ast, "unparse") else str(a) for a in node.iter.args]

                self.meta_info["loops"].append({
                    "type": "for",
                    "target": target_str,
                    "iter": iter_str,
                    "test": f"{target_str} in {iter_str}",
                    "body": body_strs,
                    "orelse": orelse_strs,
                    "is_range": is_range,
                    "range_args": range_args,
                    "has_break": any(isinstance(n, ast.Break) for n in ast.walk(node)),
                    "has_continue": any(isinstance(n, ast.Continue) for n in ast.walk(node))
                })
            elif isinstance(node, ast.If):
                is_sub_elif = False
                for p in ast.walk(tree):
                    if isinstance(p, ast.If) and len(p.orelse) == 1 and p.orelse[0] is node:
                        is_sub_elif = True
                        break
                if not is_sub_elif:
                    chain = []
                    curr = node
                    has_nested = False
                    while isinstance(curr, ast.If):
                        test_str = ast.unparse(curr.test) if hasattr(ast, "unparse") else "cond"
                        body_strs = [ast.unparse(s) for s in curr.body] if hasattr(ast, "unparse") else [str(s) for s in curr.body]

                        nested_body_ifs = [n for n in curr.body if isinstance(n, ast.If)]
                        if nested_body_ifs:
                            has_nested = True
                            nested_info = []
                            for n_if in nested_body_ifs:
                                n_test = ast.unparse(n_if.test) if hasattr(ast, "unparse") else "inner_cond"
                                n_body = [ast.unparse(s) for s in n_if.body] if hasattr(ast, "unparse") else [str(s) for s in n_if.body]
                                n_else = [ast.unparse(s) for s in n_if.orelse] if n_if.orelse and hasattr(ast, "unparse") else []
                                nested_info.append({"test": n_test, "body": n_body, "else": n_else})
                            chain.append({"type": "if_elif", "test": test_str, "body": body_strs, "nested": nested_info})
                        else:
                            chain.append({"type": "if_elif", "test": test_str, "body": body_strs})

                        if len(curr.orelse) == 1 and isinstance(curr.orelse[0], ast.If):
                            curr = curr.orelse[0]
                        else:
                            if curr.orelse:
                                else_strs = [ast.unparse(s) for s in curr.orelse] if hasattr(ast, "unparse") else [str(s) for s in curr.orelse]
                                nested_else_ifs = [n for n in curr.orelse if isinstance(n, ast.If)]
                                if nested_else_ifs:
                                    has_nested = True
                                    nested_else_info = []
                                    for n_if in nested_else_ifs:
                                        n_test = ast.unparse(n_if.test) if hasattr(ast, "unparse") else "inner_cond"
                                        n_body = [ast.unparse(s) for s in n_if.body] if hasattr(ast, "unparse") else [str(s) for s in n_if.body]
                                        n_else = [ast.unparse(s) for s in n_if.orelse] if n_if.orelse and hasattr(ast, "unparse") else []
                                        nested_else_info.append({"test": n_test, "body": n_body, "else": n_else})
                                    chain.append({"type": "else", "test": "else", "body": else_strs, "nested": nested_else_info})
                                else:
                                    chain.append({"type": "else", "test": "else", "body": else_strs})
                            break
                    if chain:
                        self.meta_info["has_conditionals"] = True
                        if has_nested:
                            self.meta_info["has_nested_conditionals"] = True
                        self.meta_info["conditionals"].append(chain)
            elif isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                
                if func_name in ("Path", "open", "read_text", "write_text", "read", "write", "writelines", "splitlines", "DictReader", "DictWriter", "dump", "dumps", "load", "loads"):
                    self.meta_info["file_ops"]["has_files"] = True

                    if func_name in ("write_text", "write", "writelines", "dump"):
                        for arg in node.args:
                            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                for l in arg.value.splitlines():
                                    if l.strip() and l not in self.meta_info["file_ops"]["code_file_content"]:
                                        self.meta_info["file_ops"]["code_file_content"].append(l)

                    if hasattr(node, "lineno") and 0 <= node.lineno - 1 < len(code_lines):
                        cline = code_lines[node.lineno - 1].strip()
                        if cline and cline not in self.meta_info["file_ops"]["file_code_lines"]:
                            self.meta_info["file_ops"]["file_code_lines"].append(cline)

                    is_write_mode = False
                    if func_name in ("write_text", "write", "writelines", "DictWriter", "dump"):
                        is_write_mode = True
                    if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                        if any(m in node.args[1].value for m in ("w", "a", "x")):
                            is_write_mode = True
                    for kw in node.keywords:
                        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                            if any(m in str(kw.value.value) for m in ("w", "a", "x")):
                                is_write_mode = True

                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            val = arg.value
                            if any(val.endswith(ext) for ext in (".txt", ".csv", ".json", ".dat", ".log", ".xml", ".md")):
                                target_names = []
                                for parent_stmt in ast.walk(tree):
                                    if isinstance(parent_stmt, ast.Assign):
                                        if any(arg in ast.walk(parent_stmt.value) for _ in [1]):
                                            for t in parent_stmt.targets:
                                                if isinstance(t, ast.Name):
                                                    target_names.append(t.id.lower())
                                if is_write_mode or any(t in ("out", "output", "dest", "res", "result", "target", "summary", "f_out", "w_file", "writer") for t in target_names) or "out" in val.lower() or "res" in val.lower():
                                    self.meta_info["file_ops"]["output_file"] = val
                                else:
                                    if not self.meta_info["file_ops"]["input_file"]:
                                        self.meta_info["file_ops"]["input_file"] = val
            elif isinstance(node, ast.ClassDef):
                base_name = "object"
                if node.bases:
                    if isinstance(node.bases[0], ast.Name):
                        base_name = node.bases[0].id
                self.meta_info["classes"][node.name] = base_name

                cls_attrs = []
                cls_methods = []
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        cls_methods.append(item.name)
                        for sub_stmt in ast.walk(item):
                            if isinstance(sub_stmt, ast.Assign):
                                for tgt in sub_stmt.targets:
                                    if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == "self":
                                        if tgt.attr not in cls_attrs and not tgt.attr.startswith("_"):
                                            cls_attrs.append(tgt.attr)
                            elif isinstance(sub_stmt, ast.AnnAssign):
                                if isinstance(sub_stmt.target, ast.Attribute) and isinstance(sub_stmt.target.value, ast.Name) and sub_stmt.target.value.id == "self":
                                    if sub_stmt.target.attr not in cls_attrs and not sub_stmt.target.attr.startswith("_"):
                                        cls_attrs.append(sub_stmt.target.attr)
                    elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                        tgts = item.targets if isinstance(item, ast.Assign) else [item.target]
                        for tgt in tgts:
                            if isinstance(tgt, ast.Name) and not tgt.id.startswith("_"):
                                if tgt.id not in cls_attrs:
                                    cls_attrs.append(tgt.id)

                self.meta_info.setdefault("class_details", {})[node.name] = {
                    "parent": base_name,
                    "attrs": cls_attrs,
                    "methods": cls_methods
                }

                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                        called = sub.func.id
                        if called in known_classes and called != node.name:
                            rel = {"type": "aggregation", "from": node.name, "to": called}
                            if rel not in self.meta_info["relations"]:
                                self.meta_info["relations"].append(rel)
                    elif isinstance(sub, ast.AnnAssign):
                        type_name = ""
                        if isinstance(sub.annotation, ast.Name):
                            type_name = sub.annotation.id
                        elif isinstance(sub.annotation, ast.Subscript) and isinstance(sub.annotation.slice, ast.Name):
                            type_name = sub.annotation.slice.id
                        if type_name in known_classes and type_name != node.name:
                            rel = {"type": "aggregation", "from": node.name, "to": type_name}
                            if rel not in self.meta_info["relations"]:
                                self.meta_info["relations"].append(rel)

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
                    if not isinstance(transformed_stmt, (ast.Return, ast.Break, ast.Continue, ast.Raise)):
                        new_body.append(self._create_step_call())
                return new_body

            def visit_Module(self, node):
                node.body = self._wrap_body(node.body)
                return node

            def visit_FunctionDef(self, node):
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

            def visit_Try(self, node):
                node.body = self._wrap_body(node.body)
                if node.finalbody:
                    node.finalbody = self._wrap_body(node.finalbody)
                if node.orelse:
                    node.orelse = self._wrap_body(node.orelse)
                return node

            def visit_With(self, node):
                node.body = self._wrap_body(node.body)
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

        if self.project_dir:
            if self.project_dir not in sys.path:
                sys.path.insert(0, self.project_dir)
            
            venv_site = os.path.join(self.project_dir, "venv", "Lib", "site-packages") if sys.platform == "win32" else os.path.join(self.project_dir, "venv", "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages")
            if os.path.exists(venv_site) and venv_site not in sys.path:
                sys.path.insert(0, venv_site)

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

        def custom_input(prompt=""):
            if not self.running:
                raise KeyboardInterrupt("Execution stopped")

            output = sys.stdout.getvalue()
            if output:
                self.output_signal.emit(output)
                sys.stdout.seek(0)
                sys.stdout.truncate(0)

            prompt_str = str(prompt)
            self.waiting_for_input = True
            self.input_requested_signal.emit(prompt_str)

            while self.running:
                try:
                    user_val = self.input_queue.get(timeout=0.08)
                    self.waiting_for_input = False
                    return user_val
                except queue.Empty:
                    if not self.running:
                        self.waiting_for_input = False
                        raise KeyboardInterrupt("Execution stopped")

            self.waiting_for_input = False
            return ""

        glob["__universal_step_hook__"] = universal_step_hook
        glob["input"] = custom_input

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

        except ModuleNotFoundError as mnf_err:
            missing_lib = mnf_err.name
            self.output_signal.emit(f"\n❌ Модуль '{missing_lib}' не знайдено.\n")
            self.missing_library_signal.emit(missing_lib)

        except KeyboardInterrupt:
            self.output_signal.emit("\n⏹ Виконання зупинено.")
        except Exception:
            self.output_signal.emit("❌ Помилка виконання:\n" + traceback.format_exc())
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            self.finished_signal.emit()


# --- Клас прямокутного динамічного блоку масиву за ТЗ ---
class AnimatedArrayBlock(QGraphicsObject):
    THEMES = {
        "normal": {"bg": "#68D391", "border": "#22543D", "text": "#000000", "width": 1.8},
        "active": {"bg": "#ECC94B", "border": "#B7791F", "text": "#000000", "width": 2.6},
        "selected": {"bg": "#ED8936", "border": "#C05621", "text": "#000000", "width": 2.6},
        "match": {"bg": "#63B3ED", "border": "#2B6CB0", "text": "#000000", "width": 2.6},
    }

    def __init__(self, value, index, width=68, height=42, parent=None):
        super().__init__(parent)
        self.value = value
        self.index = index
        self.w = float(width)
        self.h = float(height)

        self.current_theme = "normal"
        self._apply_theme("normal")
        self.index_color = QColor("#C53030")
        self.setTransformOriginPoint(self.w / 2.0, self.h / 2.0)

    def _apply_theme(self, theme_key: str):
        theme = self.THEMES.get(theme_key, self.THEMES["normal"])
        self.current_theme = theme_key
        self.bg_color = QColor(theme["bg"])
        self.border_color = QColor(theme["border"])
        self.text_color = QColor(theme["text"])
        self.border_width = theme["width"]

    def boundingRect(self) -> QRectF:
        return QRectF(-4, -4, self.w + 8, self.h + 28)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0, 0, self.w, self.h)
        painter.setPen(QPen(self.border_color, self.border_width))
        painter.setBrush(QBrush(self.bg_color))
        painter.drawRect(rect)

        painter.setPen(self.text_color)
        painter.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(self.value))

        painter.setPen(self.index_color)
        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        idx_rect = QRectF(0, self.h + 2, self.w, 18)
        painter.drawText(idx_rect, Qt.AlignmentFlag.AlignCenter, f"[{self.index}]")

    def set_value(self, val):
        if self.value != val:
            self.value = val
            self.update()

    def set_index(self, idx):
        if self.index != idx:
            self.index = idx
            self.update()

    def set_theme(self, theme_key: str):
        if self.current_theme != theme_key:
            self._apply_theme(theme_key)
            self.update()

    def set_colors(self, bg_hex, border_hex, border_w=2.4):
        self.bg_color = QColor(bg_hex)
        self.border_color = QColor(border_hex)
        self.border_width = border_w
        self.update()


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

        self.current_array_blocks = []
        self.array_title_item = None
        self.active_animations = []
        self.static_items = []

        layout = QVBoxLayout()
        layout.addWidget(self.view)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

    def _clear_static_items(self):
        for item in self.static_items:
            if item.scene() == self.scene:
                self.scene.removeItem(item)
        self.static_items.clear()

    def _draw_arrow(self, x1, y1, x2, y2, color="#000000", width=2):
        l = self.scene.addLine(x1, y1, x2, y2, QPen(QColor(color), width))
        self.static_items.append(l)

        angle = math.atan2(y2 - y1, x2 - x1)
        arrow_size = 8
        p1 = QPointF(x2, y2)
        p2 = QPointF(x2 - arrow_size * math.cos(angle - math.pi / 6), y2 - arrow_size * math.sin(angle - math.pi / 6))
        p3 = QPointF(x2 - arrow_size * math.cos(angle + math.pi / 6), y2 - arrow_size * math.sin(angle + math.pi / 6))
        
        arrow_head = QGraphicsPolygonItem(QPolygonF([p1, p2, p3]))
        arrow_head.setBrush(QBrush(QColor(color)))
        arrow_head.setPen(QPen(QColor(color)))
        self.scene.addItem(arrow_head)
        self.static_items.append(arrow_head)

    def _get_rect_intersection(self, rx, ry, rw, rh, target_x, target_y):
        cx = rx + rw / 2.0
        cy = ry + rh / 2.0
        dx = target_x - cx
        dy = target_y - cy

        if abs(dx) < 1e-5 and abs(dy) < 1e-5:
            return QPointF(cx, cy)

        hw = rw / 2.0
        hh = rh / 2.0
        scale_x = hw / abs(dx) if abs(dx) > 1e-5 else float('inf')
        scale_y = hh / abs(dy) if abs(dy) > 1e-5 else float('inf')
        scale = min(scale_x, scale_y)
        return QPointF(cx + dx * scale, cy + dy * scale)

    def _draw_aggregation_between_rects(self, r1_coords, r2_coords, color="#DD6B20", width=2):
        r1_x, r1_y, r1_w, r1_h = r1_coords
        r2_x, r2_y, r2_w, r2_h = r2_coords

        c2_x = r2_x + r2_w / 2.0
        c2_y = r2_y + r2_h / 2.0
        c1_x = r1_x + r1_w / 2.0
        c1_y = r1_h / 2.0 + r1_y

        p1 = self._get_rect_intersection(r1_x, r1_y, r1_w, r1_h, c2_x, c2_y)
        p2 = self._get_rect_intersection(r2_x, r2_y, r2_w, r2_h, c1_x, c1_y)

        x1, y1 = p1.x(), p1.y()
        x2, y2 = p2.x(), p2.y()

        pen = QPen(QColor(color), width, Qt.PenStyle.DashLine)
        l = self.scene.addLine(x1, y1, x2, y2, pen)
        self.static_items.append(l)

        angle = math.atan2(y2 - y1, x2 - x1)
        diamond_len = 12
        diamond_w = 6

        p_start = QPointF(x1, y1)
        p_side1 = QPointF(x1 + diamond_len/2 * math.cos(angle) - diamond_w * math.sin(angle),
                          y1 + diamond_len/2 * math.sin(angle) + diamond_w * math.cos(angle))
        p_far = QPointF(x1 + diamond_len * math.cos(angle),
                        y1 + diamond_len * math.sin(angle))
        p_side2 = QPointF(x1 + diamond_len/2 * math.cos(angle) + diamond_w * math.sin(angle),
                          y1 + diamond_len/2 * math.sin(angle) - diamond_w * math.cos(angle))

        diamond = QGraphicsPolygonItem(QPolygonF([p_start, p_side1, p_far, p_side2]))
        diamond.setBrush(QBrush(QColor("#FFFFFF")))
        diamond.setPen(QPen(QColor(color), 1.8))
        self.scene.addItem(diamond)
        self.static_items.append(diamond)

    def _draw_diamond(self, cx, cy, w, h, text_str, bg_color="#FEFCBF", border_color="#B7791F"):
        p_top = QPointF(cx, cy - h / 2)
        p_right = QPointF(cx + w / 2, cy)
        p_bottom = QPointF(cx, cy + h / 2)
        p_left = QPointF(cx - w / 2, cy)

        diamond = QGraphicsPolygonItem(QPolygonF([p_top, p_right, p_bottom, p_left]))
        diamond.setBrush(QBrush(QColor(bg_color)))
        diamond.setPen(QPen(QColor(border_color), 2))
        self.scene.addItem(diamond)
        self.static_items.append(diamond)

        text = QGraphicsTextItem(text_str)
        text.setDefaultTextColor(QColor("#000000"))
        text.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        text.setPos(cx - text.boundingRect().width() / 2, cy - text.boundingRect().height() / 2)
        self.scene.addItem(text)
        self.static_items.append(text)

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
        self.static_items.append(poly)

        text = QGraphicsTextItem(text_str)
        text.setDefaultTextColor(QColor("#000000"))
        text.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        text.setPos(x + w / 2 - text.boundingRect().width() / 2, y + h / 2 - text.boundingRect().height() / 2)
        self.scene.addItem(text)
        self.static_items.append(text)

    def _draw_class_card(self, x: float, y: float, w: float, cls_name: str, cls_info: dict, live_instance_attrs: dict = None, is_base: bool = False, is_standalone: bool = False, parent_attrs: list = None) -> float:
        """Малює красиву UML-картку класу з назвою, властивостями (атрибутами) та методами."""
        attrs = list(cls_info.get("attrs", [])) if cls_info else []
        methods = list(cls_info.get("methods", [])) if cls_info else []
        parent_name = cls_info.get("parent", "object") if cls_info else "object"

        prop_lines = []
        
        if is_standalone or parent_name.lower() == "object" or not parent_attrs:
            # Standalone or Base class
            all_attrs = list(attrs)
            if live_instance_attrs:
                for k in live_instance_attrs.keys():
                    if k not in all_attrs:
                        all_attrs.append(k)
            for a in all_attrs[:6]:
                if live_instance_attrs and a in live_instance_attrs:
                    val_str = str(live_instance_attrs[a])
                    if len(val_str) > 14:
                        val_str = val_str[:12] + ".."
                    prop_lines.append(f"🔹 [основна] {a} = {val_str}")
                else:
                    prop_lines.append(f"🔹 [основна] {a}")
        else:
            # Derived subclass
            main_attrs = list(parent_attrs)
            add_attrs = [a for a in attrs if a not in main_attrs]
            if live_instance_attrs:
                for k in live_instance_attrs.keys():
                    if k not in main_attrs and k not in add_attrs:
                        add_attrs.append(k)

            for a in main_attrs[:4]:
                if live_instance_attrs and a in live_instance_attrs:
                    val_str = str(live_instance_attrs[a])
                    if len(val_str) > 14:
                        val_str = val_str[:12] + ".."
                    prop_lines.append(f"🔹 [основна] {a} = {val_str}")
                else:
                    prop_lines.append(f"🔹 [основна] {a}")

            for a in add_attrs[:4]:
                if live_instance_attrs and a in live_instance_attrs:
                    val_str = str(live_instance_attrs[a])
                    if len(val_str) > 14:
                        val_str = val_str[:12] + ".."
                    prop_lines.append(f"🔸 [додаткова] {a} = {val_str}")
                else:
                    prop_lines.append(f"🔸 [додаткова] {a}")

        if not prop_lines:
            prop_lines = ["🔹 (властивості)"]

        method_lines = [f"⚙️ {m}()" for m in methods if not m.startswith("__") or m == "__init__"][:4]

        header_h = 32 if is_standalone else 28
        props_h = len(prop_lines[:6]) * 18 + 8
        methods_h = (len(method_lines) * 18 + 8) if method_lines else 0
        total_h = header_h + props_h + methods_h

        if is_standalone:
            border_col = "#2F855A"
            hdr_bg_col = "#F0FFF4"
            hdr_pen_col = "#38A169"
            title_col = "#22543D"
        elif is_base:
            border_col = "#2B6CB0"
            hdr_bg_col = "#EBF8FF"
            hdr_pen_col = "#3182CE"
            title_col = "#2B6CB0"
        else:
            border_col = "#4A5568"
            hdr_bg_col = "#EDF2F7"
            hdr_pen_col = "#CBD5E0"
            title_col = "#2D3748"

        card_rect = QGraphicsRectItem(x, y, w, total_h)
        card_rect.setBrush(QBrush(QColor("#FFFFFF")))
        card_rect.setPen(QPen(QColor(border_col), 1.8))
        self.scene.addItem(card_rect)
        self.static_items.append(card_rect)

        hdr_rect = QGraphicsRectItem(x, y, w, header_h)
        hdr_rect.setBrush(QBrush(QColor(hdr_bg_col)))
        hdr_rect.setPen(QPen(QColor(hdr_pen_col), 1.2))
        self.scene.addItem(hdr_rect)
        self.static_items.append(hdr_rect)

        if is_standalone:
            title_str = f"Class {cls_name} (окремий)"
        elif parent_name and parent_name.lower() != "object":
            title_str = f"Class {cls_name} : {parent_name}"
        else:
            title_str = f"Class {cls_name}" if cls_name.lower() != "object" else "Object"

        t_title = QGraphicsTextItem(title_str)
        t_title.setDefaultTextColor(QColor(title_col))
        t_title.setFont(QFont("Consolas", 10 if is_standalone else 11, QFont.Weight.Bold))
        t_title.setPos(x + (w - t_title.boundingRect().width()) / 2, y + 4)
        self.scene.addItem(t_title)
        self.static_items.append(t_title)

        curr_y = y + header_h + 4

        for pl in prop_lines[:6]:
            if len(pl) > 32:
                pl = pl[:30] + "..."
            t_prop = QGraphicsTextItem(pl)
            t_prop.setDefaultTextColor(QColor("#22543D" if is_standalone else "#2C5282"))
            t_prop.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            t_prop.setPos(x + 6, curr_y)
            self.scene.addItem(t_prop)
            self.static_items.append(t_prop)
            curr_y += 18

        if method_lines:
            div_line = self.scene.addLine(x, curr_y, x + w, curr_y, QPen(QColor("#E2E8F0"), 1))
            self.static_items.append(div_line)
            curr_y += 4

            for ml in method_lines:
                t_meth = QGraphicsTextItem(ml)
                t_meth.setDefaultTextColor(QColor("#4A5568"))
                t_meth.setFont(QFont("Consolas", 8))
                t_meth.setPos(x + 6, curr_y)
                self.scene.addItem(t_meth)
                self.static_items.append(t_meth)
                curr_y += 18

        return total_h

    def _draw_class_tree(self, classes_dict: dict, relations: list, start_y: int, cx: int, class_details: dict = None, variables: dict = None):
        if class_details is None:
            class_details = {}
        if variables is None:
            variables = {}

        live_class_attrs = {}
        for v_k, v_val in variables.items():
            if not v_k.startswith("_") and hasattr(v_val, "__class__"):
                c_type = v_val.__class__.__name__
                if c_type in classes_dict or c_type in class_details:
                    if c_type not in live_class_attrs:
                        live_class_attrs[c_type] = {}
                    if hasattr(v_val, "__dict__"):
                        for attr_k, attr_v in getattr(v_val, "__dict__", {}).items():
                            if not attr_k.startswith("_"):
                                live_class_attrs[c_type][attr_k] = attr_v

        known_classes = set(classes_dict.keys())
        parents = set()
        children = set()
        for cls, parent in classes_dict.items():
            if parent in known_classes:
                parents.add(parent)
                children.add(cls)

        hierarchy_classes = list(parents.union(children))
        standalone_classes = [c for c in known_classes if c not in hierarchy_classes]

        rect_map = {}
        card_w = 210
        level_gap = 50

        if hierarchy_classes and standalone_classes:
            cx_hier = cx - 130
            cx_stand = cx + 160
        else:
            cx_hier = cx
            cx_stand = cx

        max_y_reached = start_y

        # Draw Hierarchy if present
        if hierarchy_classes:
            tree = {}
            for child, parent in classes_dict.items():
                if child in hierarchy_classes:
                    tree.setdefault(parent, []).append(child)

            roots = [p for p in tree.keys() if p not in classes_dict or classes_dict[p] == "object"]
            if not roots:
                roots = ["object"]

            root_name = "Object"
            obj_w, obj_h = 130, 34
            obj_x = cx_hier - obj_w / 2
            obj_rect = QGraphicsRectItem(obj_x, start_y, obj_w, obj_h)
            obj_rect.setBrush(QBrush(QColor("#FFFFFF")))
            obj_rect.setPen(QPen(QColor("#718096"), 1.8))
            self.scene.addItem(obj_rect)
            self.static_items.append(obj_rect)
            rect_map["object"] = (obj_x, start_y, obj_w, obj_h)
            rect_map["Object"] = (obj_x, start_y, obj_w, obj_h)

            t_obj = QGraphicsTextItem(root_name)
            t_obj.setDefaultTextColor(QColor("#2D3748"))
            t_obj.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
            t_obj.setPos(obj_x + (obj_w - t_obj.boundingRect().width()) / 2, start_y + 5)
            self.scene.addItem(t_obj)
            self.static_items.append(t_obj)

            user_bases = [cls for cls in hierarchy_classes if classes_dict[cls].lower() == "object" or cls in roots]
            if not user_bases:
                user_bases = [hierarchy_classes[0]]

            y_lvl1 = start_y + obj_h + level_gap
            l1 = self.scene.addLine(cx_hier, start_y + obj_h, cx_hier, y_lvl1, QPen(QColor("#4A5568"), 1.8))
            self.static_items.append(l1)

            base_name = user_bases[0]
            base_x = cx_hier - card_w / 2
            base_info = class_details.get(base_name, {})
            base_live = live_class_attrs.get(base_name, {})
            base_parent = base_info.get("parent")
            base_parent_attrs = class_details.get(base_parent, {}).get("attrs") if (base_parent and base_parent.lower() != "object") else None

            base_h = self._draw_class_card(base_x, y_lvl1, card_w, base_name, base_info, base_live, is_base=True, parent_attrs=base_parent_attrs)
            rect_map[base_name] = (base_x, y_lvl1, card_w, base_h)

            subclasses = [cls for cls in hierarchy_classes if classes_dict.get(cls) == base_name or (cls != base_name and classes_dict.get(cls, "").lower() != "object")]

            y_lvl2 = y_lvl1 + base_h + level_gap
            max_y_reached = max(max_y_reached, y_lvl2)

            if subclasses:
                num_subs = len(subclasses)
                gap = 25
                total_w = num_subs * card_w + (num_subs - 1) * gap
                start_sub_x = cx_hier - total_w / 2

                branch_y = y_lvl1 + base_h + level_gap / 2
                l2 = self.scene.addLine(cx_hier, y_lvl1 + base_h, cx_hier, branch_y, QPen(QColor("#4A5568"), 1.8))
                self.static_items.append(l2)

                first_cx = start_sub_x + card_w / 2
                last_cx = start_sub_x + (num_subs - 1) * (card_w + gap) + card_w / 2
                l3 = self.scene.addLine(first_cx, branch_y, last_cx, branch_y, QPen(QColor("#4A5568"), 1.8))
                self.static_items.append(l3)

                for i, sub_name in enumerate(subclasses):
                    sub_cx = start_sub_x + i * (card_w + gap) + card_w / 2
                    sub_x = sub_cx - card_w / 2

                    l_sub = self.scene.addLine(sub_cx, branch_y, sub_cx, y_lvl2, QPen(QColor("#4A5568"), 1.8))
                    self.static_items.append(l_sub)

                    sub_info = class_details.get(sub_name, {})
                    sub_live = live_class_attrs.get(sub_name, {})
                    sub_parent = sub_info.get("parent", base_name)
                    sub_parent_attrs = class_details.get(sub_parent, {}).get("attrs", []) if (sub_parent and sub_parent.lower() != "object") else base_info.get("attrs", [])

                    sub_h = self._draw_class_card(sub_x, y_lvl2, card_w, sub_name, sub_info, sub_live, is_base=False, parent_attrs=sub_parent_attrs)
                    rect_map[sub_name] = (sub_x, y_lvl2, card_w, sub_h)
                    max_y_reached = max(max_y_reached, y_lvl2 + sub_h)

        # Draw Standalone Classes if present
        if standalone_classes:
            stand_y = start_y
            if not hierarchy_classes:
                root_name = "Object"
                obj_w, obj_h = 130, 34
                obj_x = cx_stand - obj_w / 2
                obj_rect = QGraphicsRectItem(obj_x, start_y, obj_w, obj_h)
                obj_rect.setBrush(QBrush(QColor("#FFFFFF")))
                obj_rect.setPen(QPen(QColor("#718096"), 1.8))
                self.scene.addItem(obj_rect)
                self.static_items.append(obj_rect)

                t_obj = QGraphicsTextItem(root_name)
                t_obj.setDefaultTextColor(QColor("#2D3748"))
                t_obj.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
                t_obj.setPos(obj_x + (obj_w - t_obj.boundingRect().width()) / 2, start_y + 5)
                self.scene.addItem(t_obj)
                self.static_items.append(t_obj)

                stand_y = start_y + obj_h + level_gap

            for i, st_name in enumerate(standalone_classes):
                st_x = cx_stand - card_w / 2
                st_info = class_details.get(st_name, {})
                st_live = live_class_attrs.get(st_name, {})

                if not hierarchy_classes:
                    l_st = self.scene.addLine(cx_stand, start_y + obj_h, cx_stand, stand_y, QPen(QColor("#A0AEC0"), 1.5, Qt.PenStyle.DashLine))
                    self.static_items.append(l_st)

                st_h = self._draw_class_card(st_x, stand_y, card_w, st_name, st_info, st_live, is_standalone=True)
                rect_map[st_name] = (st_x, stand_y, card_w, st_h)
                max_y_reached = max(max_y_reached, stand_y + st_h)
                stand_y += st_h + 30

        for rel in relations:
            src = rel.get("from")
            dst = rel.get("to")
            if src in rect_map and dst in rect_map:
                self._draw_aggregation_between_rects(rect_map[src], rect_map[dst], color="#DD6B20", width=2)

        leg_y = max_y_reached + 35
        leg_rect = QGraphicsRectItem(cx - 230, leg_y, 460, 40)
        leg_rect.setBrush(QBrush(QColor("#F7FAFC")))
        leg_rect.setPen(QPen(QColor("#CBD5E0"), 1))
        self.scene.addItem(leg_rect)
        self.static_items.append(leg_rect)

        l_leg = self.scene.addLine(cx - 215, leg_y + 20, cx - 180, leg_y + 20, QPen(QColor("#4A5568"), 1.8))
        self.static_items.append(l_leg)
        t_leg1 = QGraphicsTextItem("Успадкування (is-a)")
        t_leg1.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        t_leg1.setDefaultTextColor(QColor("#2D3748"))
        t_leg1.setPos(cx - 175, leg_y + 11)
        self.scene.addItem(t_leg1)
        self.static_items.append(t_leg1)

        sample_r1 = (cx - 40, leg_y + 12, 16, 16)
        sample_r2 = (cx - 5, leg_y + 12, 16, 16)
        self._draw_aggregation_between_rects(sample_r1, sample_r2, color="#DD6B20", width=2)

        t_leg2 = QGraphicsTextItem("Агрегація (has-a)")
        t_leg2.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        t_leg2.setDefaultTextColor(QColor("#DD6B20"))
        t_leg2.setPos(cx + 15, leg_y + 11)
        self.scene.addItem(t_leg2)
        self.static_items.append(t_leg2)

        leg_st_rect = QGraphicsRectItem(cx + 125, leg_y + 12, 16, 16)
        leg_st_rect.setBrush(QBrush(QColor("#F0FFF4")))
        leg_st_rect.setPen(QPen(QColor("#2F855A"), 1.5))
        self.scene.addItem(leg_st_rect)
        self.static_items.append(leg_st_rect)

        t_leg3 = QGraphicsTextItem("Окремий клас")
        t_leg3.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        t_leg3.setDefaultTextColor(QColor("#22543D"))
        t_leg3.setPos(cx + 145, leg_y + 11)
        self.scene.addItem(t_leg3)
        self.static_items.append(t_leg3)

    def _sync_array_blocks(self, array_name: str, new_values: list, cx: int, y: int, highlighted_indices: dict):
        arr_len = len(new_values)
        elem_w = 68
        elem_h = 42
        total_w = max(arr_len * elem_w, 100)
        start_x = cx - total_w / 2

        title_text = f"Масив / Список: {array_name} (довжина {arr_len})"
        if not self.array_title_item:
            self.array_title_item = QGraphicsTextItem(title_text)
            self.array_title_item.setDefaultTextColor(QColor("#000000"))
            self.array_title_item.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            self.scene.addItem(self.array_title_item)
        else:
            self.array_title_item.setPlainText(title_text)
        self.array_title_item.setPos(start_x, y - 26)

        old_len = len(self.current_array_blocks)

        if old_len > arr_len:
            removed_blocks = self.current_array_blocks[arr_len:]
            self.current_array_blocks = self.current_array_blocks[:arr_len]

            for block in removed_blocks:
                anim_group = QParallelAnimationGroup(self)

                anim_scale = QPropertyAnimation(block, b"scale", self)
                anim_scale.setDuration(320)
                anim_scale.setStartValue(block.scale())
                anim_scale.setEndValue(0.0)
                anim_scale.setEasingCurve(QEasingCurve.Type.InBack)

                anim_opacity = QPropertyAnimation(block, b"opacity", self)
                anim_opacity.setDuration(320)
                anim_opacity.setStartValue(block.opacity())
                anim_opacity.setEndValue(0.0)

                anim_group.addAnimation(anim_scale)
                anim_group.addAnimation(anim_opacity)

                def make_cleanup(item=block, grp=anim_group):
                    def cleanup():
                        if item.scene() == self.scene:
                            self.scene.removeItem(item)
                        if grp in self.active_animations:
                            self.active_animations.remove(grp)
                    return cleanup

                anim_group.finished.connect(make_cleanup())
                self.active_animations.append(anim_group)
                anim_group.start()

        for idx in range(min(old_len, arr_len)):
            block = self.current_array_blocks[idx]
            block.set_index(idx)
            target_pos = QPointF(start_x + idx * elem_w, y)

            if block.pos() != target_pos:
                anim_pos = QPropertyAnimation(block, b"pos", self)
                anim_pos.setDuration(280)
                anim_pos.setStartValue(block.pos())
                anim_pos.setEndValue(target_pos)
                anim_pos.setEasingCurve(QEasingCurve.Type.OutQuad)
                self.active_animations.append(anim_pos)
                anim_pos.finished.connect(lambda a=anim_pos: self.active_animations.remove(a) if a in self.active_animations else None)
                anim_pos.start()

            val_changed = (block.value != new_values[idx])
            highlight_theme = highlighted_indices.get(idx, "normal")
            block.set_theme(highlight_theme)

            if val_changed or highlight_theme != "normal":
                block.set_value(new_values[idx])
                
                seq_anim = QSequentialAnimationGroup(self)
                pulse_up = QPropertyAnimation(block, b"scale", self)
                pulse_up.setDuration(160)
                pulse_up.setStartValue(1.0)
                pulse_up.setEndValue(1.22)
                pulse_up.setEasingCurve(QEasingCurve.Type.OutQuad)

                pulse_down = QPropertyAnimation(block, b"scale", self)
                pulse_down.setDuration(160)
                pulse_down.setStartValue(1.22)
                pulse_down.setEndValue(1.0)
                pulse_down.setEasingCurve(QEasingCurve.Type.OutBounce)

                seq_anim.addAnimation(pulse_up)
                seq_anim.addAnimation(pulse_down)
                self.active_animations.append(seq_anim)
                seq_anim.finished.connect(lambda a=seq_anim: self.active_animations.remove(a) if a in self.active_animations else None)
                seq_anim.start()

        if arr_len > old_len:
            for idx in range(old_len, arr_len):
                val = new_values[idx]
                block = AnimatedArrayBlock(value=val, index=idx, width=elem_w, height=elem_h)
                target_pos = QPointF(start_x + idx * elem_w, y)
                block.setPos(target_pos)

                highlight_theme = highlighted_indices.get(idx, "normal")
                block.set_theme(highlight_theme)

                block.setScale(0.0)
                self.scene.addItem(block)
                self.current_array_blocks.append(block)

                anim_add = QPropertyAnimation(block, b"scale", self)
                anim_add.setDuration(330)
                anim_add.setStartValue(0.0)
                anim_add.setEndValue(1.0)
                anim_add.setEasingCurve(QEasingCurve.Type.OutBounce)
                self.active_animations.append(anim_add)
                anim_add.finished.connect(lambda a=anim_add: self.active_animations.remove(a) if a in self.active_animations else None)
                anim_add.start()


    def _draw_file_pipeline(self, file_info: dict, variables: dict, cx: int, y: int):
        """Динамічна візуалізація 3-хетапного файлового пайплайну:
        [ Блок 1: Що було на диску ] ──▶ [ Блок 2: Як це змінив код ] ──▶ [ Блок 3: Що записується назад у файл ]
        """
        import os

        # 1. Динамічне визначення назв файлів
        input_name = file_info.get("input_file")
        output_name = file_info.get("output_file")

        if not input_name:
            for k, v in variables.items():
                if isinstance(v, str) and any(v.endswith(ext) for ext in (".txt", ".csv", ".json", ".dat", ".log", ".xml", ".md")):
                    if any(x in k.lower() for x in ("in", "input", "src", "source", "file", "path")):
                        input_name = v
                        break
        if not input_name:
            input_name = "вхідний_файл"

        if not output_name:
            for k, v in variables.items():
                if isinstance(v, str) and any(v.endswith(ext) for ext in (".txt", ".csv", ".json", ".dat", ".log", ".xml", ".md")):
                    if any(x in k.lower() for x in ("out", "output", "dest", "res", "target", "result", "summary")) and v != input_name:
                        output_name = v
                        break
        if not output_name:
            output_name = "вихідний_файл"

        # 2. Динамічне отримання початкового вмісту файлу (Блок 1)
        raw_lines = []
        if input_name and os.path.exists(input_name):
            try:
                with open(input_name, "r", encoding="utf-8") as f_in:
                    file_text = f_in.read()
                    if file_text.strip():
                        raw_lines = file_text.splitlines()
            except Exception:
                pass

        if not raw_lines:
            for k in ("lines", "data", "content", "text", "raw_data", "file_data", "input_data", "src", "raw_lines"):
                if k in variables:
                    v = variables[k]
                    if isinstance(v, list):
                        raw_lines = [str(x) for x in v]
                    elif isinstance(v, str):
                        raw_lines = v.splitlines()
                    break

        if not raw_lines:
            str_vars = [str(v) for k, v in variables.items() if isinstance(v, str) and not k.startswith("_")]
            if str_vars:
                raw_lines = str_vars[0].splitlines()

        if not raw_lines:
            raw_lines = ["(очікування зчитання даних...)"]

        # 3. Динамічне отримання команд та процесів обробки (Блок 2)
        code_lines = file_info.get("file_code_lines", [])
        if not code_lines:
            file_var_ops = [f"{k} = {v}" for k, v in variables.items() if not k.startswith("_") and not isinstance(v, (list, dict))]
            if file_var_ops:
                code_lines = file_var_ops[:6]
            else:
                code_lines = ["# Обробка процесів коду..."]

        # 4. Динамічне отримання фінального результату (Блок 3)
        total_val = None
        if output_name and os.path.exists(output_name):
            try:
                with open(output_name, "r", encoding="utf-8") as f_out:
                    out_text = f_out.read().strip()
                    if out_text:
                        total_val = out_text
            except Exception:
                pass

        if not total_val:
            for res_key in ("total", "result", "output", "res", "summary", "out_text", "ans", "score", "count", "sum_val", "data", "report"):
                if res_key in variables:
                    total_val = str(variables[res_key])
                    break

        if not total_val:
            non_list_vars = {k: str(v) for k, v in variables.items() if not isinstance(v, (list, dict)) and not k.startswith("_")}
            if non_list_vars:
                first_k = next(iter(non_list_vars))
                total_val = f"{first_k} = {non_list_vars[first_k]}"
            else:
                total_val = "(очікування результату...)"

        # 5. Побудова графічної сцени PyQt6 (3 класичні блоки)
        title = QGraphicsTextItem("📄 Візуалізація файлових операцій та процесів")
        title.setDefaultTextColor(QColor("#004085"))
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setPos(cx - title.boundingRect().width() / 2, y)
        self.scene.addItem(title)
        self.static_items.append(title)
        y += 35


        col_w = 250
        gap = 30
        start_x = cx - (3 * col_w + 2 * gap) / 2
        y_box = y + 25

        # ======================================================================
        # БЛОК 1: Файл (початковий зміст)
        # ======================================================================
        x1 = start_x
        lbl1 = QGraphicsTextItem(f"[ Блок 1: Що було у файлі  ({input_name}) ]")
        lbl1.setDefaultTextColor(QColor("#1A202C"))
        lbl1.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        lbl1.setPos(x1 + (col_w - lbl1.boundingRect().width()) / 2, y)
        self.scene.addItem(lbl1)
        self.static_items.append(lbl1)

        box1_h = max(120, min(260, len(raw_lines) * 24 + 20))
        rect1 = QGraphicsRectItem(x1, y_box, col_w, box1_h)
        rect1.setBrush(QBrush(QColor("#1E1F22")))
        rect1.setPen(QPen(QColor("#3574F0"), 2))
        self.scene.addItem(rect1)
        self.static_items.append(rect1)

        line_y = y_box + 10
        for idx, val in enumerate(raw_lines[:9], 1):
            num_txt = QGraphicsTextItem(f"{idx}")
            num_txt.setDefaultTextColor(QColor("#718096"))
            num_txt.setFont(QFont("Consolas", 10))
            num_txt.setPos(x1 + 8, line_y)
            self.scene.addItem(num_txt)
            self.static_items.append(num_txt)

            display_val = str(val)
            if len(display_val) > 36:
                display_val = display_val[:34] + "..."

            val_txt = QGraphicsTextItem(display_val)
            val_txt.setDefaultTextColor(QColor("#68D391"))
            val_txt.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            val_txt.setPos(x1 + 32, line_y)
            self.scene.addItem(val_txt)
            self.static_items.append(val_txt)
            line_y += 24

        hand_rect = QGraphicsRectItem(x1 + 5, y_box + box1_h + 12, col_w - 10, 30)
        hand_rect.setBrush(QBrush(QColor("#FEFCBF")))
        hand_rect.setPen(QPen(QColor("#B7791F"), 1.6))
        self.scene.addItem(hand_rect)
        self.static_items.append(hand_rect)

        hand_txt = QGraphicsTextItem(f"Що було у файлі  ({input_name})")
        hand_txt.setDefaultTextColor(QColor("#744210"))
        hand_txt.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        hand_txt.setPos(x1 + (col_w - hand_txt.boundingRect().width()) / 2, y_box + box1_h + 17)
        self.scene.addItem(hand_txt)
        self.static_items.append(hand_txt)

        # ======================================================================
        # БЛОК 2: Обробка процесів
        # ======================================================================
        x2 = x1 + col_w + gap
        lbl2 = QGraphicsTextItem("[ Блок 2: Як це змінив код ]")
        lbl2.setDefaultTextColor(QColor("#1A202C"))
        lbl2.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        lbl2.setPos(x2 + (col_w - lbl2.boundingRect().width()) / 2, y)
        self.scene.addItem(lbl2)
        self.static_items.append(lbl2)

        arrow1_y = y_box + 45
        self._draw_arrow(x1 + col_w + 5, arrow1_y, x2 - 5, arrow1_y, color="#3574F0", width=2.5)

        code_file_data = list(file_info.get("code_file_content", []))

        # Динамічний збір сформованого тексту та записів процесів зі змінних коду
        extra_extracted = []
        for k, v in variables.items():
            if k.startswith("_"):
                continue
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, str) and item.strip():
                        if item not in extra_extracted:
                            extra_extracted.append(item)
                    elif isinstance(item, dict):
                        rec = " | ".join(f"{dk}: {dv}" for dk, dv in item.items())
                        if rec not in extra_extracted:
                            extra_extracted.append(rec)
            elif isinstance(v, str):
                if any(ext in v for ext in (".txt", ".csv", ".json", ".py", ".md")) and len(v.splitlines()) <= 1 and "|" not in v and ":" not in v:
                    continue
                lines_in_str = [l.strip() for l in v.splitlines() if l.strip()]
                for l in lines_in_str:
                    if l not in extra_extracted:
                        extra_extracted.append(l)

        for item in extra_extracted:
            if item not in code_file_data:
                code_file_data.append(item)

        if raw_lines == ["(очікування зчитання даних...)"] and code_file_data:
            raw_lines = code_file_data

        extra_h = (min(8, len(code_file_data)) * 20 + 25) if code_file_data else 0
        box2_h = max(120, min(340, len(code_lines[:6]) * 22 + 25 + extra_h))

        rect2 = QGraphicsRectItem(x2, y_box, col_w, box2_h)
        rect2.setBrush(QBrush(QColor("#2B2D30")))
        rect2.setPen(QPen(QColor("#4E5157"), 1.8))
        self.scene.addItem(rect2)
        self.static_items.append(rect2)

        cy_code = y_box + 10
        hdr_proc = QGraphicsTextItem("⚙️ Як код змінює дані (команди):")
        hdr_proc.setDefaultTextColor(QColor("#63B3ED"))
        hdr_proc.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        hdr_proc.setPos(x2 + 6, cy_code)
        self.scene.addItem(hdr_proc)
        self.static_items.append(hdr_proc)
        cy_code += 20

        for cline in code_lines[:6]:
            display_cline = str(cline)
            if len(display_cline) > 32:
                display_cline = display_cline[:30] + "..."

            ccolor = "#E2E8F0"
            if any(kw in display_cline for kw in ("from ", "import ", "with ", " as ", "for ", "in ", "if ", "def ")):
                ccolor = "#CC7832"
            elif any(fn in display_cline for fn in ("read_text", "write_text", "open", "Path", "splitlines", "sum", "int", "dump", "read", "write")):
                ccolor = "#68D391"
            elif '"' in display_cline or "'" in display_cline:
                ccolor = "#CE9178"

            ctxt = QGraphicsTextItem(display_cline)
            ctxt.setDefaultTextColor(QColor(ccolor))
            ctxt.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            ctxt.setPos(x2 + 6, cy_code)
            self.scene.addItem(ctxt)
            self.static_items.append(ctxt)
            cy_code += 22

        if code_file_data:
            cy_code += 4
            hdr_txt = QGraphicsTextItem("📊 Дані обробки у коді:")
            hdr_txt.setDefaultTextColor(QColor("#ECC94B"))
            hdr_txt.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            hdr_txt.setPos(x2 + 6, cy_code)
            self.scene.addItem(hdr_txt)
            self.static_items.append(hdr_txt)
            cy_code += 20

            for c_idx, c_val in enumerate(code_file_data[:8], 1):
                num_item = QGraphicsTextItem(f"{c_idx}|")
                num_item.setDefaultTextColor(QColor("#718096"))
                num_item.setFont(QFont("Consolas", 8))
                num_item.setPos(x2 + 6, cy_code)
                self.scene.addItem(num_item)
                self.static_items.append(num_item)

                display_cval = str(c_val)
                if len(display_cval) > 36:
                    display_cval = display_cval[:34] + "..."

                cval_item = QGraphicsTextItem(display_cval)
                cval_item.setDefaultTextColor(QColor("#68D391"))
                cval_item.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
                cval_item.setPos(x2 + 24, cy_code)
                self.scene.addItem(cval_item)
                self.static_items.append(cval_item)
                cy_code += 20

        proc_rect = QGraphicsRectItem(x2 + 5, y_box + box2_h + 12, col_w - 10, 30)
        proc_rect.setBrush(QBrush(QColor("#EBF8FF")))
        proc_rect.setPen(QPen(QColor("#3182CE"), 1.6))
        self.scene.addItem(proc_rect)
        self.static_items.append(proc_rect)

        proc_txt = QGraphicsTextItem("Як це змінив код")
        proc_txt.setDefaultTextColor(QColor("#2B6CB0"))
        proc_txt.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        proc_txt.setPos(x2 + (col_w - proc_txt.boundingRect().width()) / 2, y_box + box2_h + 17)
        self.scene.addItem(proc_txt)
        self.static_items.append(proc_txt)

        # ======================================================================
        # БЛОК 3: Фінальний результат
        # ======================================================================
        x3 = x2 + col_w + gap
        lbl3 = QGraphicsTextItem(f"[ Блок 3: Що записується назад у файл ({output_name}) ]")
        lbl3.setDefaultTextColor(QColor("#1A202C"))
        lbl3.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        lbl3.setPos(x3 + (col_w - lbl3.boundingRect().width()) / 2, y)
        self.scene.addItem(lbl3)
        self.static_items.append(lbl3)

        self._draw_arrow(x2 + col_w + 5, arrow1_y, x3 - 5, arrow1_y, color="#38A169", width=2.5)

        out_lines = str(total_val).splitlines() if total_val else ["(очікування результату...)"]
        box3_h = max(120, min(280, len(out_lines[:9]) * 22 + 35))
        rect3 = QGraphicsRectItem(x3, y_box, col_w, box3_h)
        rect3.setBrush(QBrush(QColor("#1E1F22")))
        rect3.setPen(QPen(QColor("#38A169"), 2))
        self.scene.addItem(rect3)
        self.static_items.append(rect3)

        out_header = QGraphicsTextItem("💾 Що записується назад у файл:")
        out_header.setDefaultTextColor(QColor("#ECC94B"))
        out_header.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        out_header.setPos(x3 + 8, y_box + 8)
        self.scene.addItem(out_header)
        self.static_items.append(out_header)

        out_y = y_box + 30
        for o_idx, o_val in enumerate(out_lines[:8], 1):
            o_num = QGraphicsTextItem(f"{o_idx}|")
            o_num.setDefaultTextColor(QColor("#718096"))
            o_num.setFont(QFont("Consolas", 8))
            o_num.setPos(x3 + 8, out_y)
            self.scene.addItem(o_num)
            self.static_items.append(o_num)

            disp_o = str(o_val)
            if len(disp_o) > 36:
                disp_o = disp_o[:34] + "..."

            o_txt = QGraphicsTextItem(disp_o)
            o_txt.setDefaultTextColor(QColor("#68D391"))
            o_txt.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            o_txt.setPos(x3 + 28, out_y)
            self.scene.addItem(o_txt)
            self.static_items.append(o_txt)
            out_y += 20

        out_lbl_rect = QGraphicsRectItem(x3 + 5, y_box + box3_h + 12, col_w - 10, 30)
        out_lbl_rect.setBrush(QBrush(QColor("#C6F6D5")))
        out_lbl_rect.setPen(QPen(QColor("#2F855A"), 1.6))
        self.scene.addItem(out_lbl_rect)
        self.static_items.append(out_lbl_rect)

        out_lbl = QGraphicsTextItem(f"Запис назад у {output_name}")
        out_lbl.setDefaultTextColor(QColor("#22543D"))
        out_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        out_lbl.setPos(x3 + (col_w - out_lbl.boundingRect().width()) / 2, y_box + box3_h + 17)
        self.scene.addItem(out_lbl)
        self.static_items.append(out_lbl)

    def _draw_loop_flowchart(self, loop_info: dict, variables: dict, cx: int, y: int):
        """Блок-схема 1: Загальний цикл for по колекції."""
        title = QGraphicsTextItem("🔄 Блок-схема: Цикл for (по колекції)")
        title.setDefaultTextColor(QColor("#004085"))
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setPos(cx - title.boundingRect().width() / 2, y)
        self.scene.addItem(title)
        self.static_items.append(title)
        y += 40

        loop_var = loop_info.get("target", "item")
        iter_expr = loop_info.get("iter", "sequence")
        loop_val = variables.get(loop_var, "")
        
        # Перевірка чи активна ітерація
        is_iterating = (loop_var in variables)

        # 1. Блок ініціалізації / початку
        b1_w, b1_h = 220, 42
        b1_x = cx - b1_w / 2
        rect1 = QGraphicsRectItem(b1_x, y, b1_w, b1_h)
        rect1.setBrush(QBrush(QColor("#BEE3F8")))
        rect1.setPen(QPen(QColor("#2B6CB0"), 1.8))
        self.scene.addItem(rect1)
        self.static_items.append(rect1)

        t1 = QGraphicsTextItem(f"Початок: for {loop_var} in {iter_expr}")
        t1.setDefaultTextColor(QColor("#000000"))
        t1.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        t1.setPos(b1_x + (b1_w - t1.boundingRect().width()) / 2, y + 10)
        self.scene.addItem(t1)
        self.static_items.append(t1)

        self._draw_arrow(cx, y + b1_h, cx, y + b1_h + 30)
        y += b1_h + 30

        # 2. Ромб умови циклу
        d_cy = y + 35
        d_w, d_h = 180, 68
        self._draw_diamond(cx, d_cy, d_w, d_h, f"Є наступний {loop_var}?", 
                           bg_color="#FEFCBF" if is_iterating else "#FFFFFF",
                           border_color="#B7791F" if is_iterating else "#718096")

        # Гілка ТАК (донизу): зелений
        lbl_yes = QGraphicsTextItem("Так (True)")
        lbl_yes.setDefaultTextColor(QColor("#276749"))
        lbl_yes.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_yes.setPos(cx + 6, d_cy + d_h / 2 + 4)
        self.scene.addItem(lbl_yes)
        self.static_items.append(lbl_yes)

        # Гілка НІ (праворуч вихід): червоний
        lbl_no = QGraphicsTextItem("Ні (False)")
        lbl_no.setDefaultTextColor(QColor("#C53030"))
        lbl_no.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_no.setPos(cx + d_w / 2 + 8, d_cy - 24)
        self.scene.addItem(lbl_no)
        self.static_items.append(lbl_no)

        exit_x = cx + d_w / 2 + 110
        self._draw_arrow(cx + d_w / 2, d_cy, exit_x, d_cy, color="#C53030", width=2)
        self._draw_arrow(exit_x, d_cy, exit_x, d_cy + 25, color="#C53030", width=2)
        self._draw_parallelogram(exit_x - 70, d_cy + 25, 145, 40, f"Кінець for {loop_var}")

        # 3. Тіло циклу (вниз) - Так (True) зелена стрілка
        body_y = d_cy + d_h / 2 + 35
        self._draw_arrow(cx, d_cy + d_h / 2, cx, body_y, color="#2F855A", width=2)

        b3_w, b3_h = 220, 42
        b3_x = cx - b3_w / 2
        rect3 = QGraphicsRectItem(b3_x, body_y, b3_w, b3_h)
        rect3.setBrush(QBrush(QColor("#C6F6D5" if is_iterating else "#F7FAFC")))
        rect3.setPen(QPen(QColor("#2F855A" if is_iterating else "#CBD5E0"), 2 if is_iterating else 1.4))
        self.scene.addItem(rect3)
        self.static_items.append(rect3)

        val_repr = repr(loop_val)
        if len(val_repr) > 15:
            val_repr = val_repr[:13] + "..."
        t3 = QGraphicsTextItem(f"Тіло: {loop_var} = {val_repr}")
        t3.setDefaultTextColor(QColor("#22543D" if is_iterating else "#1A202C"))
        t3.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        t3.setPos(b3_x + 14, body_y + 10)
        self.scene.addItem(t3)
        self.static_items.append(t3)

        if is_iterating:
            tag = QGraphicsTextItem("✓ ВИКОНУЄТЬСЯ")
            tag.setDefaultTextColor(QColor("#276749"))
            tag.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            tag.setPos(b3_x + b3_w + 8, body_y + 11)
            self.scene.addItem(tag)
            self.static_items.append(tag)

        # 4. Блок модифікованих змінних
        b4_y = body_y + b3_h + 25
        self._draw_arrow(cx, body_y + b3_h, cx, b4_y)
        b4_w, b4_h = 240, 42
        b4_x = cx - b4_w / 2
        rect4 = QGraphicsRectItem(b4_x, b4_y, b4_w, b4_h)
        rect4.setBrush(QBrush(QColor("#E2E8F0")))
        rect4.setPen(QPen(QColor("#4A5568"), 1.8))
        self.scene.addItem(rect4)
        self.static_items.append(rect4)

        other_vars = [f"{k}={repr(v)}" for k, v in variables.items() if k != loop_var and not k.startswith("_") and not isinstance(v, (list, dict))]
        sub_text = ", ".join(other_vars) if other_vars else f"Елемент: {val_repr}"
        if len(sub_text) > 28:
            sub_text = sub_text[:26] + "..."
        t4 = QGraphicsTextItem(f"Стан: {sub_text}")
        t4.setDefaultTextColor(QColor("#000000"))
        t4.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        t4.setPos(b4_x + 10, b4_y + 10)
        self.scene.addItem(t4)
        self.static_items.append(t4)

        # 5. Зворотна дуга зліва назад напряму ДО РОМБА (cx - d_w / 2, d_cy)
        loop_left_x = cx - 160
        pen_loop = QPen(QColor("#000000"), 2)
        l_lp1 = self.scene.addLine(cx, b4_y + b4_h, cx, b4_y + b4_h + 18, pen_loop)
        l_lp2 = self.scene.addLine(cx, b4_y + b4_h + 18, loop_left_x, b4_y + b4_h + 18, pen_loop)
        l_lp3 = self.scene.addLine(loop_left_x, b4_y + b4_h + 18, loop_left_x, d_cy, pen_loop)
        self.static_items.extend([l_lp1, l_lp2, l_lp3])

        self._draw_arrow(loop_left_x, d_cy, cx - d_w / 2, d_cy, color="#000000", width=2)

        return b4_y + b4_h + 40

    def _draw_conditional_flowchart(self, cond_chain: list, variables: dict, cx: int, y: int):
        """Побудова 1-в-1 діаграми розгалуження (if / elif / else) за макетом."""
        title = QGraphicsTextItem("🔀 Архітектура умовного розгалуження (if / elif / else)")
        title.setDefaultTextColor(QColor("#004085"))
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setPos(cx - title.boundingRect().width() / 2, y)
        self.scene.addItem(title)
        self.static_items.append(title)
        y += 35

        init_vars = [f"{k} = {v}" for k, v in variables.items() if not k.startswith("_") and not isinstance(v, (list, dict))]
        start_code_text = ", ".join(init_vars) if init_vars else "var = 0"

        if_elif_branches = [b for b in cond_chain if b["type"] == "if_elif"]
        else_branch = next((b for b in cond_chain if b["type"] == "else"), None)
        num_if = len(if_elif_branches)

        if num_if == 0:
            return

        dx = 175
        dy = 80
        d_w, d_h = 130, 54
        box_w, box_h = 130, 48

        start_d_x = cx - ((num_if - 1) * dx) / 2
        y_start = y

        b_start_w, b_start_h = 160, 34
        b_start_x = start_d_x - b_start_w / 2
        rect_start = QGraphicsRectItem(b_start_x, y_start, b_start_w, b_start_h)
        rect_start.setBrush(QBrush(QColor("#BEE3F8")))
        rect_start.setPen(QPen(QColor("#2B6CB0"), 1.8))
        self.scene.addItem(rect_start)
        self.static_items.append(rect_start)

        t_start = QGraphicsTextItem(start_code_text)
        t_start.setDefaultTextColor(QColor("#000000"))
        t_start.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        t_start.setPos(b_start_x + (b_start_w - t_start.boundingRect().width()) / 2, y_start + 5)
        self.scene.addItem(t_start)
        self.static_items.append(t_start)

        start_d_y = y_start + b_start_h + 45 + d_h / 2

        self._draw_arrow(start_d_x, y_start + b_start_h, start_d_x, start_d_y - d_h / 2, color="#2B6CB0", width=2)

        active_idx = -1
        for idx, branch in enumerate(cond_chain):
            if branch["type"] == "if_elif":
                try:
                    res = eval(branch["test"], {}, variables)
                    if bool(res):
                        active_idx = idx
                        break
                except Exception:
                    pass
            elif branch["type"] == "else":
                if active_idx == -1:
                    active_idx = idx

        diamond_coords = []
        box_data = []

        for i, b in enumerate(if_elif_branches):
            cd_x = start_d_x + i * dx
            cd_y = start_d_y + i * dy
            diamond_coords.append((cd_x, cd_y))

            is_diamond_active = (i == active_idx)
            is_evaluated_false = (not is_diamond_active and i < active_idx)
            bg_d = "#FEFCBF" if is_diamond_active else "#FFFFFF"
            border_d = "#B7791F" if is_diamond_active else ("#C53030" if is_evaluated_false else "#718096")
            self._draw_diamond(cd_x, cd_y, d_w, d_h, f"{b['test']} ?", bg_color=bg_d, border_color=border_d)

            left_turn_x = cd_x - d_w / 2 - 40
            box_x = left_turn_x
            box_y = cd_y + 40
            box_data.append((box_x, box_y, b, i == active_idx, False))

            tak_color = "#2F855A" if is_diamond_active else "#CBD5E0"
            l_tak = self.scene.addLine(cd_x - d_w / 2, cd_y, left_turn_x, cd_y, QPen(QColor(tak_color), 2 if is_diamond_active else 1.5))
            self.static_items.append(l_tak)

            self._draw_arrow(left_turn_x, cd_y, left_turn_x, box_y, color=tak_color, width=2 if is_diamond_active else 1.5)

            lbl_tak = QGraphicsTextItem("так")
            lbl_tak.setDefaultTextColor(QColor("#276749"))
            lbl_tak.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            tak_mid_x = (cd_x - d_w / 2 + left_turn_x) / 2
            lbl_tak.setPos(tak_mid_x - lbl_tak.boundingRect().width() / 2, cd_y - 20)
            self.scene.addItem(lbl_tak)
            self.static_items.append(lbl_tak)

            if i < num_if - 1:
                next_cd_x = start_d_x + (i + 1) * dx
                next_cd_y = start_d_y + (i + 1) * dy
                # Стрілка Ні (False) - завжди яскраво червона
                self._draw_arrow(cd_x + d_w / 2, cd_y, next_cd_x, cd_y, color="#C53030", width=2.5 if is_evaluated_false else 2)
                self._draw_arrow(next_cd_x, cd_y, next_cd_x, next_cd_y - d_h / 2, color="#C53030", width=2.5 if is_evaluated_false else 2)

                lbl_ni = QGraphicsTextItem("ні")
                lbl_ni.setDefaultTextColor(QColor("#C53030"))
                lbl_ni.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                ni_mid_x = (cd_x + d_w / 2 + next_cd_x) / 2
                lbl_ni.setPos(ni_mid_x - lbl_ni.boundingRect().width() / 2, cd_y - 20)
                self.scene.addItem(lbl_ni)
                self.static_items.append(lbl_ni)
            else:
                if else_branch:
                    right_turn_x = cd_x + d_w / 2 + 40
                    else_box_x = right_turn_x
                    else_box_y = cd_y + 40
                    is_else_active = (active_idx == num_if)
                    box_data.append((else_box_x, else_box_y, else_branch, is_else_active, True))

                    # Стрілка Ні (False) у блок else - завжди яскраво червона
                    self._draw_arrow(cd_x + d_w / 2, cd_y, right_turn_x, cd_y, color="#C53030", width=2.5 if is_else_active else 2)
                    self._draw_arrow(right_turn_x, cd_y, right_turn_x, else_box_y, color="#C53030", width=2.5 if is_else_active else 2)

                    lbl_ni = QGraphicsTextItem("ні")
                    lbl_ni.setDefaultTextColor(QColor("#C53030"))
                    lbl_ni.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                    ni_mid_x = (cd_x + d_w / 2 + right_turn_x) / 2
                    lbl_ni.setPos(ni_mid_x - lbl_ni.boundingRect().width() / 2, cd_y - 20)
                    self.scene.addItem(lbl_ni)
                    self.static_items.append(lbl_ni)

        box_bottom_coords = []

        for bx_x, bx_y, b_info, is_act, is_else in box_data:
            rect_b = QGraphicsRectItem(bx_x - box_w / 2, bx_y, box_w, box_h)
            rect_b.setBrush(QBrush(QColor("#C6F6D5" if is_act else "#F7FAFC")))
            rect_b.setPen(QPen(QColor("#2F855A" if is_act else "#CBD5E0"), 2 if is_act else 1.4))
            self.scene.addItem(rect_b)
            self.static_items.append(rect_b)

            b_text = "; ".join(b_info["body"])
            if len(b_text) > 22:
                b_text = b_text[:20] + "..."

            prefix = "else:\n" if is_else else ""
            display_str = prefix + b_text
            t_b = QGraphicsTextItem(display_str)
            t_b.setDefaultTextColor(QColor("#22543D" if is_act else "#1A202C"))
            t_b.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            t_b.setPos(bx_x - box_w / 2 + (box_w - t_b.boundingRect().width()) / 2, bx_y + (box_h - t_b.boundingRect().height()) / 2)
            self.scene.addItem(t_b)
            self.static_items.append(t_b)

            if is_act:
                tag_b = QGraphicsTextItem("✓ ВИКОНУЄТЬСЯ")
                tag_b.setDefaultTextColor(QColor("#276749"))
                tag_b.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                tag_b.setPos(bx_x + box_w / 2 + 8, bx_y + 14)
                self.scene.addItem(tag_b)
                self.static_items.append(tag_b)

            box_bottom_coords.append((bx_x, bx_y + box_h))

        if len(box_bottom_coords) >= 2:
            max_box_y = max(c[1] for c in box_bottom_coords)
            merge_y_start = max_box_y + 25

            right1_x, right1_y = box_bottom_coords[-1]
            right2_x, right2_y = box_bottom_coords[-2]

            m_y1 = merge_y_start
            l_b1 = self.scene.addLine(right1_x, right1_y, right1_x, m_y1, QPen(QColor("#4A5568"), 1.6))
            l_b2 = self.scene.addLine(right2_x, right2_y, right2_x, m_y1, QPen(QColor("#4A5568"), 1.6))
            h_m1 = self.scene.addLine(right2_x, m_y1, right1_x, m_y1, QPen(QColor("#4A5568"), 1.6))
            self.static_items.extend([l_b1, l_b2, h_m1])

            mid_x1 = (right1_x + right2_x) / 2
            curr_mid_x = mid_x1
            curr_m_y = m_y1

            for idx in range(len(box_bottom_coords) - 3, -1, -1):
                bx_x, bx_y = box_bottom_coords[idx]
                next_m_y = curr_m_y + 22

                v_prev = self.scene.addLine(curr_mid_x, curr_m_y, curr_mid_x, next_m_y, QPen(QColor("#4A5568"), 1.6))
                v_curr = self.scene.addLine(bx_x, bx_y, bx_x, next_m_y, QPen(QColor("#4A5568"), 1.6))
                h_curr = self.scene.addLine(bx_x, next_m_y, curr_mid_x, next_m_y, QPen(QColor("#4A5568"), 1.6))

                self.static_items.extend([v_prev, v_curr, h_curr])

                curr_mid_x = (bx_x + curr_mid_x) / 2
                curr_m_y = next_m_y

    def _draw_while_loop_flowchart(self, loop_info: dict, variables: dict, cx: int, y: int):
        """Блок-схема 3: Класичний цикл із передумовою (while)."""
        title = QGraphicsTextItem("🔄 Блок-схема: Цикл із передумовою (while)")
        title.setDefaultTextColor(QColor("#004085"))
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setPos(cx - title.boundingRect().width() / 2, y)
        self.scene.addItem(title)
        self.static_items.append(title)
        y += 40

        test_expr = loop_info.get("test", "умова") if loop_info else "умова"
        
        # Динамічне визначення змінної циклу з виразу умови
        tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", test_expr)
        candidates = [t for t in tokens if t in variables and t not in ("True", "False", "None", "len", "range", "int", "float", "str")]
        if candidates:
            loop_var = candidates[0]
        else:
            num_vars = [k for k, v in variables.items() if isinstance(v, (int, float)) and not k.startswith("_")]
            loop_var = num_vars[0] if num_vars else loop_info.get("target", "i")

        loop_val = variables.get(loop_var, 0)

        # Оцінка умови в реальному часі
        is_cond_true = True
        try:
            is_cond_true = bool(eval(test_expr, {}, variables))
        except Exception:
            pass

        # 1. Початок / Ініціалізація
        b1_w, b1_h = 200, 42
        b1_x = cx - b1_w / 2
        rect1 = QGraphicsRectItem(b1_x, y, b1_w, b1_h)
        rect1.setBrush(QBrush(QColor("#BEE3F8")))
        rect1.setPen(QPen(QColor("#2B6CB0"), 1.8))
        self.scene.addItem(rect1)
        self.static_items.append(rect1)

        t1 = QGraphicsTextItem(f"Початок: {loop_var} = {loop_val}")
        t1.setDefaultTextColor(QColor("#000000"))
        t1.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        t1.setPos(b1_x + (b1_w - t1.boundingRect().width()) / 2, y + 8)
        self.scene.addItem(t1)
        self.static_items.append(t1)

        self._draw_arrow(cx, y + b1_h, cx, y + b1_h + 30)

        # 2. Ромб перевірки передумови
        d_cy = y + b1_h + 30 + 35
        d_w, d_h = 170, 70
        self._draw_diamond(cx, d_cy, d_w, d_h, f"while {test_expr} ?",
                           bg_color="#FEFCBF" if is_cond_true else "#FFFFFF",
                           border_color="#B7791F" if is_cond_true else "#C53030")

        # Гілка ТАК (донизу): зелений
        lbl_yes = QGraphicsTextItem("Так (True)")
        lbl_yes.setDefaultTextColor(QColor("#276749"))
        lbl_yes.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_yes.setPos(cx + 6, d_cy + d_h / 2 + 4)
        self.scene.addItem(lbl_yes)
        self.static_items.append(lbl_yes)

        # Гілка НІ (праворуч вихід): червоний
        lbl_no = QGraphicsTextItem("Ні (False)")
        lbl_no.setDefaultTextColor(QColor("#C53030"))
        lbl_no.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_no.setPos(cx + d_w / 2 + 8, d_cy - 24)
        self.scene.addItem(lbl_no)
        self.static_items.append(lbl_no)

        # Гілка False (Вихід) - ЧЕРВОНА
        exit_x = cx + d_w / 2 + 110
        self._draw_arrow(cx + d_w / 2, d_cy, exit_x, d_cy, color="#C53030", width=2.5 if not is_cond_true else 2)
        self._draw_arrow(exit_x, d_cy, exit_x, d_cy + 25, color="#C53030", width=2.5 if not is_cond_true else 2)
        self._draw_parallelogram(exit_x - 70, d_cy + 25, 150, 40, "Вихід з циклу while",
                                bg_color="#FED7D7" if not is_cond_true else "#EDF2F7",
                                border_color="#C53030" if not is_cond_true else "#718096")

        if not is_cond_true:
            exit_tag = QGraphicsTextItem("✓ ЗАВЕРШЕНО")
            exit_tag.setDefaultTextColor(QColor("#C53030"))
            exit_tag.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            exit_tag.setPos(exit_x + 85, d_cy + 35)
            self.scene.addItem(exit_tag)
            self.static_items.append(exit_tag)

        # 3. Виконання операторів (тіло циклу) - ЗЕЛЕНА стрілка
        body_y = d_cy + d_h / 2 + 35
        self._draw_arrow(cx, d_cy + d_h / 2, cx, body_y, color="#2F855A", width=2.5 if is_cond_true else 1.5)

        b3_w, b3_h = 200, 42
        b3_x = cx - b3_w / 2
        rect3 = QGraphicsRectItem(b3_x, body_y, b3_w, b3_h)
        rect3.setBrush(QBrush(QColor("#C6F6D5" if is_cond_true else "#F7FAFC")))
        rect3.setPen(QPen(QColor("#2F855A" if is_cond_true else "#CBD5E0"), 2 if is_cond_true else 1.4))
        self.scene.addItem(rect3)
        self.static_items.append(rect3)

        t3 = QGraphicsTextItem(f"Тіло: {loop_var} = {loop_val}")
        t3.setDefaultTextColor(QColor("#22543D" if is_cond_true else "#1A202C"))
        t3.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        t3.setPos(b3_x + 18, body_y + 10)
        self.scene.addItem(t3)
        self.static_items.append(t3)

        if is_cond_true:
            tag3 = QGraphicsTextItem("✓ ВИКОНУЄТЬСЯ")
            tag3.setDefaultTextColor(QColor("#276749"))
            tag3.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            tag3.setPos(b3_x + b3_w + 8, body_y + 11)
            self.scene.addItem(tag3)
            self.static_items.append(tag3)

        self._draw_arrow(cx, body_y + b3_h, cx, body_y + b3_h + 25)

        # 4. Модифікація параметрів
        b4_y = body_y + b3_h + 25
        b4_w, b4_h = 240, 42
        b4_x = cx - b4_w / 2
        rect4 = QGraphicsRectItem(b4_x, b4_y, b4_w, b4_h)
        rect4.setBrush(QBrush(QColor("#E2E8F0")))
        rect4.setPen(QPen(QColor("#4A5568"), 1.8))
        self.scene.addItem(rect4)
        self.static_items.append(rect4)

        other_vars = [f"{k}={v}" for k, v in variables.items() if k != loop_var and not k.startswith("_") and not isinstance(v, list)]
        sub_text = ", ".join(other_vars) if other_vars else f"Поточний {loop_var} = {loop_val}"
        if len(sub_text) > 28:
            sub_text = sub_text[:26] + "..."
        t4 = QGraphicsTextItem(f"Стан: {sub_text}")
        t4.setDefaultTextColor(QColor("#000000"))
        t4.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        t4.setPos(b4_x + 10, b4_y + 10)
        self.scene.addItem(t4)
        self.static_items.append(t4)

        # 5. Повторення процесу: зворотна дуга зліва вгору ДО РОМБА (cx - d_w / 2, d_cy)
        loop_left_x = cx - 160
        pen_loop = QPen(QColor("#000000"), 2)
        l_lp1 = self.scene.addLine(cx, b4_y + b4_h, cx, b4_y + b4_h + 18, pen_loop)
        l_lp2 = self.scene.addLine(cx, b4_y + b4_h + 18, loop_left_x, b4_y + b4_h + 18, pen_loop)
        l_lp3 = self.scene.addLine(loop_left_x, b4_y + b4_h + 18, loop_left_x, d_cy, pen_loop)
        self.static_items.extend([l_lp1, l_lp2, l_lp3])

        # Стрілочка від лівої лінії з'єднується напряму з ромбом у точці (cx - d_w / 2, d_cy)
        self._draw_arrow(loop_left_x, d_cy, cx - d_w / 2, d_cy, color="#000000", width=2)

        return b4_y + b4_h + 40

    def _draw_while_true_break_continue_flowchart(self, loop_info: dict, variables: dict, cx: int, y: int):
        """Блок-схема 4: Цикл з післяумовою / while True (з break та continue)."""
        title = QGraphicsTextItem("🔄 Блок-схема: Цикл з післяумовою / while True (break & continue)")
        title.setDefaultTextColor(QColor("#004085"))
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setPos(cx - title.boundingRect().width() / 2, y)
        self.scene.addItem(title)
        self.static_items.append(title)
        y += 40

        break_cond = loop_info.get("break_cond") if loop_info else None
        if not break_cond:
            break_cond = "умова_виходу"

        continue_cond = loop_info.get("continue_cond") if loop_info else None

        # Оцінка умов в реальному часі
        is_break_active = False
        if break_cond and break_cond != "умова_виходу":
            try:
                is_break_active = bool(eval(break_cond, {}, variables))
            except Exception:
                pass

        is_continue_active = False
        if continue_cond and not is_break_active:
            try:
                is_continue_active = bool(eval(continue_cond, {}, variables))
            except Exception:
                pass

        # 1. Початок циклу
        b1_w, b1_h = 220, 42
        b1_x = cx - b1_w / 2
        rect1 = QGraphicsRectItem(b1_x, y, b1_w, b1_h)
        rect1.setBrush(QBrush(QColor("#BEE3F8")))
        rect1.setPen(QPen(QColor("#2B6CB0"), 1.8))
        self.scene.addItem(rect1)
        self.static_items.append(rect1)

        t1 = QGraphicsTextItem("Початок: while True:")
        t1.setDefaultTextColor(QColor("#000000"))
        t1.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        t1.setPos(b1_x + (b1_w - t1.boundingRect().width()) / 2, y + 8)
        self.scene.addItem(t1)
        self.static_items.append(t1)

        self._draw_arrow(cx, y + b1_h, cx, y + b1_h + 25)
        y += b1_h + 25

        # 2. Тіло циклу (перша частина)
        b2_w, b2_h = 220, 40
        b2_x = cx - b2_w / 2
        rect2 = QGraphicsRectItem(b2_x, y, b2_w, b2_h)
        rect2.setBrush(QBrush(QColor("#EBF8FF")))
        rect2.setPen(QPen(QColor("#3182CE"), 1.8))
        self.scene.addItem(rect2)
        self.static_items.append(rect2)

        t2 = QGraphicsTextItem("⚙️ Виконання дій ітерації")
        t2.setDefaultTextColor(QColor("#2B6CB0"))
        t2.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        t2.setPos(b2_x + 18, y + 8)
        self.scene.addItem(t2)
        self.static_items.append(t2)

        self._draw_arrow(cx, y + b2_h, cx, y + b2_h + 30)
        y += b2_h + 30

        # 3. Перевірка умови (if break)
        d1_cy = y + 35
        d1_w, d1_h = 170, 68
        self._draw_diamond(cx, d1_cy, d1_w, d1_h, f"if {break_cond} ?",
                           bg_color="#FEFCBF" if is_break_active else "#FFFFFF",
                           border_color="#B7791F" if is_break_active else "#CBD5E0")

        # Гілка виходу (праворуч) - Так (True) зелена лінія для виходу через break
        lbl_br_yes = QGraphicsTextItem("Так (True)")
        lbl_br_yes.setDefaultTextColor(QColor("#276749"))
        lbl_br_yes.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_br_yes.setPos(cx + d1_w / 2 + 8, d1_cy - 24)
        self.scene.addItem(lbl_br_yes)
        self.static_items.append(lbl_br_yes)

        exit_x = cx + d1_w / 2 + 120
        l_br = self.scene.addLine(cx + d1_w / 2, d1_cy, exit_x, d1_cy, QPen(QColor("#2F855A" if is_break_active else "#CBD5E0"), 2 if is_break_active else 1.5))
        self.static_items.append(l_br)

        rect_br = QGraphicsRectItem(exit_x - 40, d1_cy + 25, 80, 32)
        rect_br.setBrush(QBrush(QColor("#C6F6D5" if is_break_active else "#F7FAFC")))
        rect_br.setPen(QPen(QColor("#2F855A" if is_break_active else "#CBD5E0"), 2 if is_break_active else 1.4))
        self.scene.addItem(rect_br)
        self.static_items.append(rect_br)

        t_br = QGraphicsTextItem("break")
        t_br.setDefaultTextColor(QColor("#22543D" if is_break_active else "#718096"))
        t_br.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        t_br.setPos(exit_x - 22, d1_cy + 29)
        self.scene.addItem(t_br)
        self.static_items.append(t_br)

        self._draw_arrow(exit_x, d1_cy, exit_x, d1_cy + 25, color="#2F855A" if is_break_active else "#CBD5E0", width=2 if is_break_active else 1.5)
        self._draw_arrow(exit_x, d1_cy + 25 + 32, exit_x, d1_cy + 25 + 32 + 25, color="#2F855A" if is_break_active else "#CBD5E0", width=2 if is_break_active else 1.5)

        self._draw_parallelogram(exit_x - 80, d1_cy + 25 + 32 + 25, 160, 40, "Вихід з циклу (break)",
                                bg_color="#C6F6D5" if is_break_active else "#EDF2F7",
                                border_color="#2F855A" if is_break_active else "#718096")

        if is_break_active:
            br_tag = QGraphicsTextItem("✓ СПРАЦЮВАВ BREAK")
            br_tag.setDefaultTextColor(QColor("#276749"))
            br_tag.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            br_tag.setPos(exit_x + 85, d1_cy + 25 + 32 + 35)
            self.scene.addItem(br_tag)
            self.static_items.append(br_tag)

        # Гілка продовження (вниз) - Ні (False) червона
        lbl_br_no = QGraphicsTextItem("Ні (False)")
        lbl_br_no.setDefaultTextColor(QColor("#C53030"))
        lbl_br_no.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_br_no.setPos(cx + 6, d1_cy + d1_h / 2 + 4)
        self.scene.addItem(lbl_br_no)
        self.static_items.append(lbl_br_no)

        y_next = d1_cy + d1_h / 2 + 35
        # Стрілка Ні (False) продовження циклу вниз - завжди червона
        self._draw_arrow(cx, d1_cy + d1_h / 2, cx, y_next, color="#C53030", width=2.5 if not is_break_active else 2)

        if continue_cond:
            d2_cy = y_next + 35
            d2_w, d2_h = 170, 68
            self._draw_diamond(cx, d2_cy, d2_w, d2_h, f"if {continue_cond} ?",
                               bg_color="#FEFCBF" if is_continue_active else "#FFFFFF",
                               border_color="#B7791F" if is_continue_active else "#CBD5E0")

            # Гілка continue (ліворуч) - Так (True) зелена
            lbl_cnt_yes = QGraphicsTextItem("Так (True)")
            lbl_cnt_yes.setDefaultTextColor(QColor("#276749"))
            lbl_cnt_yes.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            lbl_cnt_yes.setPos(cx - d2_w / 2 - 80, d2_cy - 24)
            self.scene.addItem(lbl_cnt_yes)
            self.static_items.append(lbl_cnt_yes)

            cnt_left_x = cx - d2_w / 2 - 120
            cnt_color = "#2F855A" if is_continue_active else "#CBD5E0"
            l_cnt = self.scene.addLine(cx - d2_w / 2, d2_cy, cnt_left_x, d2_cy, QPen(QColor(cnt_color), 2 if is_continue_active else 1.5))
            l_cnt_up = self.scene.addLine(cnt_left_x, d2_cy, cnt_left_x, d1_cy, QPen(QColor(cnt_color), 2 if is_continue_active else 1.5))
            self.static_items.extend([l_cnt, l_cnt_up])
            # З'єднання стрілочки continue з ромбом d1
            self._draw_arrow(cnt_left_x, d1_cy, cx - d1_w / 2, d1_cy, color=cnt_color, width=2 if is_continue_active else 1.5)

            # Гілка далі вниз - Ні (False) червона
            lbl_cnt_no = QGraphicsTextItem("Ні (False)")
            lbl_cnt_no.setDefaultTextColor(QColor("#C53030"))
            lbl_cnt_no.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            lbl_cnt_no.setPos(cx + 6, d2_cy + d2_h / 2 + 4)
            self.scene.addItem(lbl_cnt_no)
            self.static_items.append(lbl_cnt_no)

            y_next = d2_cy + d2_h / 2 + 35
            # Стрілка Ні (False) продовження вниз повз continue - завжди червона
            self._draw_arrow(cx, d2_cy + d2_h / 2, cx, y_next, color="#C53030", width=2.5 if not is_continue_active else 2)

        # 4. Фінальні оператори та зворотна дуга напряму ДО РОМБА d1 (cx - d1_w / 2, d1_cy)
        b5_w, b5_h = 220, 40
        b5_x = cx - b5_w / 2
        rect5 = QGraphicsRectItem(b5_x, y_next, b5_w, b5_h)
        is_normal_active = (not is_break_active and not is_continue_active)
        rect5.setBrush(QBrush(QColor("#E2E8F0" if is_normal_active else "#F7FAFC")))
        rect5.setPen(QPen(QColor("#4A5568" if is_normal_active else "#CBD5E0"), 1.8))
        self.scene.addItem(rect5)
        self.static_items.append(rect5)

        other_vars = [f"{k}={v}" for k, v in variables.items() if not k.startswith("_") and not isinstance(v, (list, dict))]
        sub_text = ", ".join(other_vars) if other_vars else "ітерація триває"
        if len(sub_text) > 26:
            sub_text = sub_text[:24] + "..."
        t5 = QGraphicsTextItem(f"Стан: {sub_text}")
        t5.setDefaultTextColor(QColor("#2D3748"))
        t5.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        t5.setPos(b5_x + 10, y_next + 8)
        self.scene.addItem(t5)
        self.static_items.append(t5)

        loop_left_x = cx - 170
        pen_loop = QPen(QColor("#000000" if is_normal_active else "#CBD5E0"), 2)
        l_lp1 = self.scene.addLine(cx, y_next + b5_h, cx, y_next + b5_h + 20, pen_loop)
        l_lp2 = self.scene.addLine(cx, y_next + b5_h + 20, loop_left_x, y_next + b5_h + 20, pen_loop)
        l_lp3 = self.scene.addLine(loop_left_x, y_next + b5_h + 20, loop_left_x, d1_cy, pen_loop)
        self.static_items.extend([l_lp1, l_lp2, l_lp3])

        # З'єднання лівої стрілочки безпосередньо з ромбом у точці (cx - d1_w / 2, d1_cy)
        self._draw_arrow(loop_left_x, d1_cy, cx - d1_w / 2, d1_cy, color="#000000" if is_normal_active else "#CBD5E0", width=2)

        return y_next + b5_h + 40

    def _draw_for_range_flowchart(self, loop_info: dict, variables: dict, cx: int, y: int):
        """Блок-схема 5: Цикл із лічильником (for var in range(start, end, step))."""
        title = QGraphicsTextItem("🔢 Блок-схема: Цикл із лічильником (for in range)")
        title.setDefaultTextColor(QColor("#004085"))
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setPos(cx - title.boundingRect().width() / 2, y)
        self.scene.addItem(title)
        self.static_items.append(title)
        y += 40

        var_name = loop_info.get("target", "i") if loop_info else "i"
        var_val = variables.get(var_name, 0)

        range_args = loop_info.get("range_args", []) if loop_info else []
        if len(range_args) == 1:
            start_str, end_str, step_str = "0", range_args[0], "1"
        elif len(range_args) == 2:
            start_str, end_str, step_str = range_args[0], range_args[1], "1"
        elif len(range_args) >= 3:
            start_str, end_str, step_str = range_args[0], range_args[1], range_args[2]
        else:
            start_str, end_str, step_str = "0", "10", "1"

        try:
            step_val = eval(step_str, {}, variables)
            end_val = eval(end_str, {}, variables)
        except Exception:
            step_val = 1
            end_val = 10

        if step_val > 0:
            is_active_iter = (var_name in variables and var_val < end_val)
            comp_sym = "<"
        else:
            is_active_iter = (var_name in variables and var_val > end_val)
            comp_sym = ">"

        # 1. Ініціалізація лічильника
        b1_w, b1_h = 220, 42
        b1_x = cx - b1_w / 2
        rect1 = QGraphicsRectItem(b1_x, y, b1_w, b1_h)
        rect1.setBrush(QBrush(QColor("#BEE3F8")))
        rect1.setPen(QPen(QColor("#2B6CB0"), 1.8))
        self.scene.addItem(rect1)
        self.static_items.append(rect1)

        t1 = QGraphicsTextItem(f"Ініціалізація: {var_name} = {start_str}")
        t1.setDefaultTextColor(QColor("#000000"))
        t1.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        t1.setPos(b1_x + (b1_w - t1.boundingRect().width()) / 2, y + 8)
        self.scene.addItem(t1)
        self.static_items.append(t1)

        self._draw_arrow(cx, y + b1_h, cx, y + b1_h + 30)

        # 2. Ромб перевірки лічильника
        d_cy = y + b1_h + 30 + 35
        d_w, d_h = 170, 70
        self._draw_diamond(cx, d_cy, d_w, d_h, f"{var_name} {comp_sym} {end_str} ?",
                           bg_color="#FEFCBF" if is_active_iter else "#FFFFFF",
                           border_color="#B7791F" if is_active_iter else "#CBD5E0")

        # Гілка ТАК (донизу): зелений
        lbl_yes = QGraphicsTextItem("Так (True)")
        lbl_yes.setDefaultTextColor(QColor("#276749"))
        lbl_yes.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_yes.setPos(cx + 6, d_cy + d_h / 2 + 4)
        self.scene.addItem(lbl_yes)
        self.static_items.append(lbl_yes)

        # Гілка НІ (праворуч вихід): червоний
        lbl_no = QGraphicsTextItem("Ні (False)")
        lbl_no.setDefaultTextColor(QColor("#C53030"))
        lbl_no.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_no.setPos(cx + d_w / 2 + 8, d_cy - 24)
        self.scene.addItem(lbl_no)
        self.static_items.append(lbl_no)

        # Гілка False (Вихід) - ЧЕРВОНА
        exit_x = cx + d_w / 2 + 110
        self._draw_arrow(cx + d_w / 2, d_cy, exit_x, d_cy, color="#C53030", width=2.5 if not is_active_iter else 2)
        self._draw_arrow(exit_x, d_cy, exit_x, d_cy + 25, color="#C53030", width=2.5 if not is_active_iter else 2)
        self._draw_parallelogram(exit_x - 70, d_cy + 25, 150, 40, "Завершення range",
                                bg_color="#FED7D7" if not is_active_iter and var_name in variables else "#EDF2F7",
                                border_color="#C53030" if not is_active_iter and var_name in variables else "#718096")

        # 3. Виконання дій тіла циклу - ЗЕЛЕНА стрілка
        body_y = d_cy + d_h / 2 + 35
        self._draw_arrow(cx, d_cy + d_h / 2, cx, body_y, color="#2F855A", width=2.5 if is_active_iter else 1.5)

        b3_w, b3_h = 220, 40
        b3_x = cx - b3_w / 2
        rect3 = QGraphicsRectItem(b3_x, body_y, b3_w, b3_h)
        rect3.setBrush(QBrush(QColor("#C6F6D5" if is_active_iter else "#F7FAFC")))
        rect3.setPen(QPen(QColor("#2F855A" if is_active_iter else "#CBD5E0"), 2 if is_active_iter else 1.4))
        self.scene.addItem(rect3)
        self.static_items.append(rect3)

        t3 = QGraphicsTextItem(f"Тіло: {var_name} = {var_val}")
        t3.setDefaultTextColor(QColor("#22543D" if is_active_iter else "#1A202C"))
        t3.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        t3.setPos(b3_x + 18, body_y + 8)
        self.scene.addItem(t3)
        self.static_items.append(t3)

        if is_active_iter:
            tag3 = QGraphicsTextItem("✓ ВИКОНУЄТЬСЯ")
            tag3.setDefaultTextColor(QColor("#276749"))
            tag3.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            tag3.setPos(b3_x + b3_w + 8, body_y + 10)
            self.scene.addItem(tag3)
            self.static_items.append(tag3)

        self._draw_arrow(cx, body_y + b3_h, cx, body_y + b3_h + 25)

        # 4. Приріст лічильника (var += step)
        b4_y = body_y + b3_h + 25
        b4_w, b4_h = 220, 42
        b4_x = cx - b4_w / 2
        rect4 = QGraphicsRectItem(b4_x, b4_y, b4_w, b4_h)
        rect4.setBrush(QBrush(QColor("#C6F6D5" if is_active_iter else "#F7FAFC")))
        rect4.setPen(QPen(QColor("#2F855A" if is_active_iter else "#CBD5E0"), 1.8 if is_active_iter else 1.4))
        self.scene.addItem(rect4)
        self.static_items.append(rect4)

        t4 = QGraphicsTextItem(f"Приріст: {var_name} += {step_str}")
        t4.setDefaultTextColor(QColor("#22543D" if is_active_iter else "#1A202C"))
        t4.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        t4.setPos(b4_x + 16, b4_y + 9)
        self.scene.addItem(t4)
        self.static_items.append(t4)

        # 5. Зворотна дуга зліва напряму ДО РОМБА (cx - d_w / 2, d_cy)
        loop_left_x = cx - 160
        pen_loop = QPen(QColor("#000000"), 2)
        l_lp1 = self.scene.addLine(cx, b4_y + b4_h, cx, b4_y + b4_h + 18, pen_loop)
        l_lp2 = self.scene.addLine(cx, b4_y + b4_h + 18, loop_left_x, b4_y + b4_h + 18, pen_loop)
        l_lp3 = self.scene.addLine(loop_left_x, b4_y + b4_h + 18, loop_left_x, d_cy, pen_loop)
        self.static_items.extend([l_lp1, l_lp2, l_lp3])

        # Стрілочка від лівої лінії з'єднується напряму з ромбом у точці (cx - d_w / 2, d_cy)
        self._draw_arrow(loop_left_x, d_cy, cx - d_w / 2, d_cy, color="#000000", width=2)

        return b4_y + b4_h + 40

    def _draw_nested_conditional_flowchart(self, cond_chain: list, variables: dict, cx: int, y: int):
        """Блок-схема 6: Вкладені умовні розгалуження (Nested If / Multilevel Elif)."""
        title = QGraphicsTextItem("🔀 Блок-схема: Вкладені розгалуження (Nested If)")
        title.setDefaultTextColor(QColor("#004085"))
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setPos(cx - title.boundingRect().width() / 2, y)
        self.scene.addItem(title)
        self.static_items.append(title)
        y += 40

        outer_branch = cond_chain[0] if cond_chain else {"test": "умова_1", "body": ["pass"]}
        outer_test = outer_branch.get("test", "умова_1")

        nested_info = outer_branch.get("nested", [])
        inner_branch = nested_info[0] if nested_info else {"test": "вкладена_умова", "body": ["pass"]}
        inner_test = inner_branch.get("test", "вкладена_умова")

        # Оцінка умов в реальному часі на основі змінних!
        try:
            outer_val = bool(eval(outer_test, {}, variables))
        except Exception:
            outer_val = True

        inner_val = None
        if outer_val:
            try:
                inner_val = bool(eval(inner_test, {}, variables))
            except Exception:
                inner_val = True

        # Визначення активної гілки:
        # active_block: "in_true" (1.1), "in_false" (1.2), or "out_false" (2)
        if outer_val and inner_val:
            active_block = "in_true"
        elif outer_val and not inner_val:
            active_block = "in_false"
        else:
            active_block = "out_false"

        # 1. Вхід / Зовнішній стан
        init_vars = [f"{k} = {v}" for k, v in variables.items() if not k.startswith("_") and not isinstance(v, (list, dict))]
        start_code_text = ", ".join(init_vars) if init_vars else "стан змінних"
        if len(start_code_text) > 30:
            start_code_text = start_code_text[:28] + "..."

        b_start_w, b_start_h = 180, 36
        b_start_x = cx - b_start_w / 2
        rect_start = QGraphicsRectItem(b_start_x, y, b_start_w, b_start_h)
        rect_start.setBrush(QBrush(QColor("#BEE3F8")))
        rect_start.setPen(QPen(QColor("#2B6CB0"), 1.8))
        self.scene.addItem(rect_start)
        self.static_items.append(rect_start)

        t_start = QGraphicsTextItem(start_code_text)
        t_start.setDefaultTextColor(QColor("#000000"))
        t_start.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        t_start.setPos(b_start_x + (b_start_w - t_start.boundingRect().width()) / 2, y + 6)
        self.scene.addItem(t_start)
        self.static_items.append(t_start)

        self._draw_arrow(cx, y + b_start_h, cx, y + b_start_h + 30)
        y += b_start_h + 30

        # 2. Зовнішній ромб умови 1
        d1_cy = y + 35
        d1_w, d1_h = 180, 68
        self._draw_diamond(cx, d1_cy, d1_w, d1_h, f"if {outer_test} ?",
                           bg_color="#FEFCBF",
                           border_color="#B7791F" if outer_val else "#C53030")

        # Гілка Зовнішній True (зліва) - ЗЕЛЕНА
        outer_true_x = cx - d1_w / 2 - 110
        out_t_color = "#2F855A" if outer_val else "#CBD5E0"
        l_out_t = self.scene.addLine(cx - d1_w / 2, d1_cy, outer_true_x, d1_cy, QPen(QColor(out_t_color), 2 if outer_val else 1.5))
        self.static_items.append(l_out_t)

        lbl_ot = QGraphicsTextItem("Так (True)")
        lbl_ot.setDefaultTextColor(QColor("#276749"))
        lbl_ot.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_ot.setPos((cx - d1_w / 2 + outer_true_x) / 2 - 25, d1_cy - 20)
        self.scene.addItem(lbl_ot)
        self.static_items.append(lbl_ot)

        self._draw_arrow(outer_true_x, d1_cy, outer_true_x, d1_cy + 35, color=out_t_color, width=2 if outer_val else 1.5)

        # 3. Внутрішній ромб перевірки вкладеної умови 1.1
        d2_cy = d1_cy + 35 + 35
        d2_w, d2_h = 170, 68
        self._draw_diamond(outer_true_x, d2_cy, d2_w, d2_h, f"if {inner_test} ?",
                           bg_color="#FEFCBF" if outer_val else "#FFFFFF",
                           border_color="#B7791F" if (outer_val and inner_val) else ("#C53030" if (outer_val and not inner_val) else "#CBD5E0"))

        # Вкладений True (донизу) - ЗЕЛЕНИЙ
        in_true_y = d2_cy + d2_h / 2 + 35
        in_t_color = "#2F855A" if active_block == "in_true" else "#CBD5E0"
        self._draw_arrow(outer_true_x, d2_cy + d2_h / 2, outer_true_x, in_true_y, color=in_t_color, width=2 if active_block == "in_true" else 1.5)

        lbl_it = QGraphicsTextItem("Так (True)")
        lbl_it.setDefaultTextColor(QColor("#276749"))
        lbl_it.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_it.setPos(outer_true_x + 6, d2_cy + d2_h / 2 + 4)
        self.scene.addItem(lbl_it)
        self.static_items.append(lbl_it)

        b_in_t_w, b_in_t_h = 160, 42
        rect_in_t = QGraphicsRectItem(outer_true_x - b_in_t_w / 2, in_true_y, b_in_t_w, b_in_t_h)
        rect_in_t.setBrush(QBrush(QColor("#C6F6D5" if active_block == "in_true" else "#F7FAFC")))
        rect_in_t.setPen(QPen(QColor("#2F855A" if active_block == "in_true" else "#CBD5E0"), 2 if active_block == "in_true" else 1.4))
        self.scene.addItem(rect_in_t)
        self.static_items.append(rect_in_t)

        in_body_text = "; ".join(inner_branch.get("body", ["pass"]))
        if len(in_body_text) > 20: in_body_text = in_body_text[:18] + "..."
        t_in_t = QGraphicsTextItem(f"Блок 1.1: {in_body_text}")
        t_in_t.setDefaultTextColor(QColor("#22543D" if active_block == "in_true" else "#1A202C"))
        t_in_t.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        t_in_t.setPos(outer_true_x - b_in_t_w / 2 + 8, in_true_y + 10)
        self.scene.addItem(t_in_t)
        self.static_items.append(t_in_t)

        if active_block == "in_true":
            tag1 = QGraphicsTextItem("✓ ВИКОНУЄТЬСЯ")
            tag1.setDefaultTextColor(QColor("#276749"))
            tag1.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            tag1.setPos(outer_true_x + b_in_t_w / 2 + 6, in_true_y + 12)
            self.scene.addItem(tag1)
            self.static_items.append(tag1)

        # Вкладений False / else (праворуч від вкладеного ромба) - ЧЕРВОНИЙ
        in_false_x = outer_true_x + d2_w / 2 + 80
        # Стрілка Ні (False) для вкладеного ромба - завжди червона
        self._draw_arrow(outer_true_x + d2_w / 2, d2_cy, in_false_x, d2_cy, color="#C53030", width=2.5 if active_block == "in_false" else 2)
        self._draw_arrow(in_false_x, d2_cy, in_false_x, in_true_y, color="#C53030", width=2.5 if active_block == "in_false" else 2)

        lbl_if = QGraphicsTextItem("Ні (False)")
        lbl_if.setDefaultTextColor(QColor("#C53030"))
        lbl_if.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_if.setPos((outer_true_x + d2_w / 2 + in_false_x) / 2 - 20, d2_cy - 20)
        self.scene.addItem(lbl_if)
        self.static_items.append(lbl_if)

        rect_in_f = QGraphicsRectItem(in_false_x - b_in_t_w / 2, in_true_y, b_in_t_w, b_in_t_h)
        rect_in_f.setBrush(QBrush(QColor("#C6F6D5" if active_block == "in_false" else "#F7FAFC")))
        rect_in_f.setPen(QPen(QColor("#2F855A" if active_block == "in_false" else "#CBD5E0"), 2 if active_block == "in_false" else 1.4))
        self.scene.addItem(rect_in_f)
        self.static_items.append(rect_in_f)

        else_body_text = "; ".join(inner_branch.get("else", ["pass"])) if inner_branch.get("else") else "вкладений else"
        if len(else_body_text) > 20: else_body_text = else_body_text[:18] + "..."
        t_in_f = QGraphicsTextItem(f"Блок 1.2: {else_body_text}")
        t_in_f.setDefaultTextColor(QColor("#22543D" if active_block == "in_false" else "#1A202C"))
        t_in_f.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        t_in_f.setPos(in_false_x - b_in_t_w / 2 + 8, in_true_y + 10)
        self.scene.addItem(t_in_f)
        self.static_items.append(t_in_f)

        if active_block == "in_false":
            tag2 = QGraphicsTextItem("✓ ВИКОНУЄТЬСЯ")
            tag2.setDefaultTextColor(QColor("#276749"))
            tag2.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            tag2.setPos(in_false_x + b_in_t_w / 2 + 6, in_true_y + 12)
            self.scene.addItem(tag2)
            self.static_items.append(tag2)

        # 4. Гілка Зовнішній False (праворуч від зовнішнього ромба) - ЧЕРВОНА
        outer_false_x = cx + d1_w / 2 + 130
        # Стрілка Ні (False) для зовнішнього ромба - завжди червона
        self._draw_arrow(cx + d1_w / 2, d1_cy, outer_false_x, d1_cy, color="#C53030", width=2.5 if active_block == "out_false" else 2)

        lbl_of = QGraphicsTextItem("Ні (False)")
        lbl_of.setDefaultTextColor(QColor("#C53030"))
        lbl_of.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_of.setPos((cx + d1_w / 2 + outer_false_x) / 2 - 25, d1_cy - 20)
        self.scene.addItem(lbl_of)
        self.static_items.append(lbl_of)

        self._draw_arrow(outer_false_x, d1_cy, outer_false_x, in_true_y, color="#C53030", width=2.5 if active_block == "out_false" else 2)

        rect_out_f = QGraphicsRectItem(outer_false_x - b_in_t_w / 2, in_true_y, b_in_t_w, b_in_t_h)
        rect_out_f.setBrush(QBrush(QColor("#C6F6D5" if active_block == "out_false" else "#F7FAFC")))
        rect_out_f.setPen(QPen(QColor("#2F855A" if active_block == "out_false" else "#CBD5E0"), 2 if active_block == "out_false" else 1.4))
        self.scene.addItem(rect_out_f)
        self.static_items.append(rect_out_f)

        t_out_f = QGraphicsTextItem("Блок 2: зовнішній else")
        t_out_f.setDefaultTextColor(QColor("#22543D" if active_block == "out_false" else "#1A202C"))
        t_out_f.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        t_out_f.setPos(outer_false_x - b_in_t_w / 2 + 8, in_true_y + 10)
        self.scene.addItem(t_out_f)
        self.static_items.append(t_out_f)

        if active_block == "out_false":
            tag3 = QGraphicsTextItem("✓ ВИКОНУЄТЬСЯ")
            tag3.setDefaultTextColor(QColor("#276749"))
            tag3.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            tag3.setPos(outer_false_x + b_in_t_w / 2 + 6, in_true_y + 12)
            self.scene.addItem(tag3)
            self.static_items.append(tag3)

        # 5. Зведення всіх гілок в одну точку внизу
        merge_y = in_true_y + b_in_t_h + 30
        l_m1 = self.scene.addLine(outer_true_x, in_true_y + b_in_t_h, outer_true_x, merge_y, QPen(QColor("#718096"), 1.5))
        l_m2 = self.scene.addLine(in_false_x, in_true_y + b_in_t_h, in_false_x, merge_y, QPen(QColor("#718096"), 1.5))
        l_m3 = self.scene.addLine(outer_false_x, in_true_y + b_in_t_h, outer_false_x, merge_y, QPen(QColor("#718096"), 1.5))
        h_m = self.scene.addLine(outer_true_x, merge_y, outer_false_x, merge_y, QPen(QColor("#718096"), 1.5))
        self.static_items.extend([l_m1, l_m2, l_m3, h_m])

        return merge_y + 30

    def update_variables(self, variables: dict, meta_info: dict):
        self._clear_static_items()

        has_classes = bool(meta_info.get("classes"))
        has_loops = meta_info.get("has_loops", False)
        file_info = meta_info.get("file_ops", {})
        has_files = file_info.get("has_files", False)
        has_conditionals = meta_info.get("has_conditionals", False)
        primary = meta_info.get("primary_structure")

        cx = max(380, self.view.width() // 2)
        y = 30

        highlight_map = {}
        for var_name in ("i", "j", "k", "current_idx"):
            if var_name in variables and isinstance(variables[var_name], int):
                highlight_map[variables[var_name]] = "active"

        for var_name in ("min_index", "max_index", "key_index"):
            if var_name in variables and isinstance(variables[var_name], int):
                highlight_map[variables[var_name]] = "selected"

        for var_name in ("found_idx", "target"):
            if var_name in variables and isinstance(variables[var_name], int):
                highlight_map[variables[var_name]] = "match"

        list_entry = next(((k, v) for k, v in variables.items() if isinstance(v, list)), None)
        if list_entry:
            arr_name, arr_val = list_entry
            self._sync_array_blocks(arr_name, arr_val, cx, y, highlight_map)
            y += 42 + 45
        else:
            if self.current_array_blocks:
                for b in self.current_array_blocks:
                    if b.scene() == self.scene:
                        self.scene.removeItem(b)
                self.current_array_blocks.clear()
            if self.array_title_item and self.array_title_item.scene() == self.scene:
                self.scene.removeItem(self.array_title_item)
                self.array_title_item = None

        if has_files:
            self._draw_file_pipeline(file_info, variables, cx, y)
        elif has_classes:
            title = QGraphicsTextItem("Ієрархія класів (ООП)")
            title.setDefaultTextColor(QColor("#004085"))
            title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            title.setPos(cx - title.boundingRect().width() / 2, y - 10)
            self.scene.addItem(title)
            self.static_items.append(title)

            self._draw_class_tree(meta_info["classes"], meta_info.get("relations", []), y + 20, cx, meta_info.get("class_details", {}), variables)

        elif primary == "conditional" or (has_conditionals and not has_loops):
            cond_chains = meta_info.get("conditionals", [])
            if cond_chains:
                if meta_info.get("has_nested_conditionals"):
                    self._draw_nested_conditional_flowchart(cond_chains[0], variables, cx, y)
                else:
                    self._draw_conditional_flowchart(cond_chains[0], variables, cx, y)

        elif has_loops:
            loops_list = meta_info.get("loops", [])
            loop_info = loops_list[0] if loops_list else {}

            # Точне розрізнення 4 типів циклів:
            if loop_info.get("type") == "while" and (loop_info.get("is_while_true") or loop_info.get("has_break") or loop_info.get("has_continue")):
                self._draw_while_true_break_continue_flowchart(loop_info, variables, cx, y)
            elif loop_info.get("type") == "while":
                self._draw_while_loop_flowchart(loop_info, variables, cx, y)
            elif loop_info.get("type") == "for" and loop_info.get("is_range"):
                self._draw_for_range_flowchart(loop_info, variables, cx, y)
            else:
                self._draw_loop_flowchart(loop_info, variables, cx, y)

        elif has_conditionals:
            cond_chains = meta_info.get("conditionals", [])
            if cond_chains:
                if meta_info.get("has_nested_conditionals"):
                    self._draw_nested_conditional_flowchart(cond_chains[0], variables, cx, y)
                else:
                    self._draw_conditional_flowchart(cond_chains[0], variables, cx, y)

        else:
            var_w, var_h = 140, 42
            spacing = 35
            prev_center = None

            non_list_vars = {k: v for k, v in variables.items() if not isinstance(v, list)}

            if not non_list_vars:
                empty_lbl = QGraphicsTextItem("Операції над масивом виконано.")
                empty_lbl.setDefaultTextColor(QColor("#004085"))
                empty_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
                empty_lbl.setPos(cx - empty_lbl.boundingRect().width() / 2, y + 10)
                self.scene.addItem(empty_lbl)
                self.static_items.append(empty_lbl)
                return

            for name, val in non_list_vars.items():
                vx = cx - var_w / 2
                rect = QGraphicsRectItem(vx, y, var_w, var_h)
                rect.setBrush(QBrush(QColor("#BEE3F8")))
                rect.setPen(QPen(QColor("#2B6CB0"), 1.8))
                self.scene.addItem(rect)
                self.static_items.append(rect)

                val_str = str(val)
                if hasattr(val, '__class__') and val.__class__.__name__ not in ('int', 'float', 'str', 'bool'):
                    val_str = f"<{val.__class__.__name__}>"

                vt = QGraphicsTextItem(f"{name} = {val_str}")
                vt.setDefaultTextColor(QColor("#000000"))
                vt.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
                vt.setPos(vx + 10, y + 10)
                self.scene.addItem(vt)
                self.static_items.append(vt)

                desc = self.VARIABLE_TERMS.get(name, "Локальна змінна")
                side_lbl = QGraphicsTextItem(f"◀ {desc}")
                side_lbl.setDefaultTextColor(QColor("#4A5568"))
                side_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                side_lbl.setPos(vx + var_w + 10, y + 10)
                self.scene.addItem(side_lbl)
                self.static_items.append(side_lbl)

                if prev_center:
                    self._draw_arrow(prev_center[0], prev_center[1], vx + var_w / 2, y)

                prev_center = (vx + var_w / 2, y + var_h)
                y += var_h + spacing

class OutputTextEdit(QPlainTextEdit):
    input_submitted = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.waiting_for_input = False
        self.prompt_pos = 0
        self.setStyleSheet("""
            background-color: #1e1e1e;
            color: #bbbbbb;
            font: 10pt Consolas;
            border-top: 1px solid #444;
        """)

    def append_output(self, text: str):
        self.moveCursor(QTextCursor.MoveOperation.End)
        self.insertPlainText(text)
        self.ensureCursorVisible()

    def start_input_session(self, prompt: str):
        self.waiting_for_input = True
        self.setReadOnly(False)
        self.moveCursor(QTextCursor.MoveOperation.End)
        if prompt:
            self.insertPlainText(prompt)
        self.prompt_pos = self.textCursor().position()
        self.ensureCursorVisible()
        self.setFocus()

    def stop_input_session(self):
        self.waiting_for_input = False
        self.setReadOnly(True)

    def keyPressEvent(self, event: QKeyEvent):
        if not self.waiting_for_input:
            super().keyPressEvent(event)
            return

        cursor = self.textCursor()

        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            doc_text = self.toPlainText()
            user_input = doc_text[self.prompt_pos:]
            self.stop_input_session()
            self.append_output("\n")
            self.input_submitted.emit(user_input)
            event.accept()
            return

        if event.key() == Qt.Key.Key_Backspace:
            if cursor.position() <= self.prompt_pos:
                event.accept()
                return

        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            if cursor.position() <= self.prompt_pos:
                event.accept()
                return

        if cursor.position() < self.prompt_pos:
            self.moveCursor(QTextCursor.MoveOperation.End)

        super().keyPressEvent(event)


# --- Діалог створення проєкту у стилі PyCharm New Project ---
class PyCharmNewProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.resize(560, 280)
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2d30;
                color: #dfdfdf;
                font-family: 'Segoe UI';
                font-size: 10pt;
            }
            QLabel {
                color: #dfdfdf;
            }
            QLineEdit {
                background-color: #1e1f22;
                color: #ffffff;
                border: 1px solid #4e5157;
                border-radius: 4px;
                padding: 6px 8px;
            }
            QLineEdit:focus {
                border: 1px solid #3574f0;
            }
            QPushButton {
                background-color: #3574f0;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3069db;
            }
            QGroupBox {
                border: 1px solid #4e5157;
                border-radius: 6px;
                margin-top: 14px;
                padding-top: 12px;
                font-weight: bold;
                color: #dfdfdf;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QCheckBox {
                color: #dfdfdf;
            }
        """)

        layout = QVBoxLayout()

        form_layout = QFormLayout()
        self.location_edit = QLineEdit()
        default_dir = os.path.join(os.path.expanduser("~"), "PyCharmProjects", "pythonProject")
        self.location_edit.setText(default_dir)

        browse_btn = QPushButton("📁")
        browse_btn.setFixedWidth(40)
        browse_btn.clicked.connect(self.browse_location)

        loc_layout = QHBoxLayout()
        loc_layout.addWidget(self.location_edit)
        loc_layout.addWidget(browse_btn)
        form_layout.addRow("Location:", loc_layout)
        layout.addLayout(form_layout)

        venv_group = QGroupBox("Python Interpreter: New Virtualenv environment")
        venv_layout = QVBoxLayout()

        self.venv_checkbox = QCheckBox("New environment using Virtualenv (створити venv)")
        self.venv_checkbox.setChecked(True)
        venv_layout.addWidget(self.venv_checkbox)

        self.main_file_checkbox = QCheckBox("Create a main.py script (без коду)")
        self.main_file_checkbox.setChecked(True)
        venv_layout.addWidget(self.main_file_checkbox)

        venv_group.setLayout(venv_layout)
        layout.addWidget(venv_group)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        create_btn = QPushButton("Create")
        create_btn.setDefault(True)
        create_btn.clicked.connect(self.accept)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("background-color: #4e5157;")
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(create_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def browse_location(self):
        chosen_dir = QFileDialog.getExistingDirectory(self, "Виберіть папку для проєкту")
        if chosen_dir:
            self.location_edit.setText(os.path.join(chosen_dir, "pythonProject"))

    def get_data(self):
        return {
            "path": self.location_edit.text().strip(),
            "create_venv": self.venv_checkbox.isChecked(),
            "create_main": self.main_file_checkbox.isChecked()
        }


# --- Перше стартове вікно у стилі PyCharm Welcome Screen з активними вкладками ---
class PyCharmWelcomeWindow(QWidget):
    project_selected = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Welcome to Python Studio")
        self.setFixedSize(800, 560)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint
        )

        screen_geo = QApplication.primaryScreen().availableGeometry()
        x = (screen_geo.width() - 800) // 2
        y = (screen_geo.height() - 560) // 2
        self.move(x, y)

        self.setStyleSheet("""
            QWidget {
                background-color: #2b2d30;
                color: #dfdfdf;
                font-family: 'Segoe UI';
            }
        """)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Ліва бічна панель (Sidebar)
        sidebar = QFrame()
        sidebar.setFixedWidth(210)
        sidebar.setStyleSheet("background-color: #1e1f22; border-right: 1px solid #393b40;")
        sb_layout = QVBoxLayout()
        sb_layout.setContentsMargins(15, 20, 15, 20)
        sb_layout.setSpacing(6)

        logo_label = QLabel("🐍 <b>Python Studio</b>")
        logo_label.setStyleSheet("font-size: 13pt; color: #ffffff; padding-bottom: 15px;")
        sb_layout.addWidget(logo_label)

        self.btn_projects = QPushButton("Projects")
        self.btn_customize = QPushButton("Customize")
        self.btn_plugins = QPushButton("Plugins")
        self.btn_learn = QPushButton("Learn Python")

        self.nav_buttons = [self.btn_projects, self.btn_customize, self.btn_plugins, self.btn_learn]
        for idx, btn in enumerate(self.nav_buttons):
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, i=idx: self.switch_tab(i))
            sb_layout.addWidget(btn)

        sb_layout.addStretch()

        btn_settings = QPushButton("⚙")
        btn_settings.setStyleSheet("background: transparent; color: #9aa0a6; font-size: 14pt; border: none; text-align: left; padding: 6px;")
        btn_settings.clicked.connect(self.show_quick_settings)
        sb_layout.addWidget(btn_settings)

        sidebar.setLayout(sb_layout)
        main_layout.addWidget(sidebar)

        # Права зона з вкладками (QStackedWidget)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.create_projects_page())
        self.stack.addWidget(self.create_customize_page())
        self.stack.addWidget(self.create_plugins_page())
        self.stack.addWidget(self.create_learn_page())

        main_layout.addWidget(self.stack)
        self.setLayout(main_layout)

        self.switch_tab(0)

    def switch_tab(self, index):
        self.stack.setCurrentIndex(index)
        btn_active = "text-align: left; background-color: #3574f0; color: #ffffff; padding: 8px 12px; border-radius: 4px; font-weight: bold; border: none;"
        btn_normal = "text-align: left; background: transparent; color: #9aa0a6; padding: 8px 12px; border-radius: 4px; font-weight: 500; border: none;"
        for i, btn in enumerate(self.nav_buttons):
            btn.setStyleSheet(btn_active if i == index else btn_normal)

    def show_quick_settings(self):
        QMessageBox.information(
            self,
            "Параметри",
            "Python Studio 2026.1\n\nБазова конфігурація середовища активна.\nДля детального налаштування використовуйте розділ Customize."
        )

    # 1. Сторінка Projects (чистий екран без нижньої плашки)
    def create_projects_page(self):
        page = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(40, 50, 40, 40)
        layout.setSpacing(15)

        title = QLabel("Welcome to Python Studio")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 22pt; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)

        subtitle = QLabel("Create a new project to start from scratch.\nOpen existing project from disk or version control.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("font-size: 10pt; color: #8c9099; margin-bottom: 25px;")
        layout.addWidget(subtitle)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(25)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        def make_action_card(icon_str, title_str, bg_color="#3574f0"):
            btn = QPushButton(f"{icon_str}\n\n{title_str}")
            btn.setFixedSize(115, 105)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #1e1f22;
                    border: 1px solid #393b40;
                    border-radius: 8px;
                    color: #dfdfdf;
                    font-size: 10pt;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    border: 1px solid {bg_color};
                    background-color: #26282d;
                }}
            """)
            return btn

        btn_new = make_action_card("➕", "New Project")
        btn_open = make_action_card("📁", "Open")
        btn_vcs = make_action_card("🔀", "Get from VCS")

        btn_new.clicked.connect(self.on_new_project)
        btn_open.clicked.connect(self.on_open_project)
        btn_vcs.clicked.connect(self.on_open_project)

        actions_layout.addWidget(btn_new)
        actions_layout.addWidget(btn_open)
        actions_layout.addWidget(btn_vcs)
        layout.addLayout(actions_layout)

        layout.addStretch()

        page.setLayout(layout)
        return page

    # 2. Сторінка Customize (налаштування)
    def create_customize_page(self):
        page = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        header = QLabel("<h2>Customize</h2>")
        header.setStyleSheet("color: #ffffff;")
        layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(15)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark (Darcula / Modern Dark)", "Light (IntelliJ Light)", "High Contrast", "System default"])
        self.theme_combo.setStyleSheet("background-color: #1e1f22; color: #ffffff; padding: 6px; border: 1px solid #4e5157; border-radius: 4px;")
        form.addRow("Color theme:", self.theme_combo)

        self.font_combo = QComboBox()
        self.font_combo.addItems(["11 pt (Default)", "12 pt", "14 pt", "16 pt"])
        self.font_combo.setStyleSheet("background-color: #1e1f22; color: #ffffff; padding: 6px; border: 1px solid #4e5157; border-radius: 4px;")
        form.addRow("IDE font size:", self.font_combo)

        self.keymap_combo = QComboBox()
        self.keymap_combo.addItems(["Windows (Default)", "macOS", "Visual Studio Code", "Sublime Text", "Emacs"])
        self.keymap_combo.setStyleSheet("background-color: #1e1f22; color: #ffffff; padding: 6px; border: 1px solid #4e5157; border-radius: 4px;")
        form.addRow("Keymap:", self.keymap_combo)

        layout.addLayout(form)
        layout.addStretch()

        apply_btn = QPushButton("Apply Settings")
        apply_btn.setFixedSize(140, 36)
        apply_btn.setStyleSheet("background-color: #3574f0; color: #ffffff; font-weight: bold; border-radius: 4px; border: none;")
        apply_btn.clicked.connect(lambda: QMessageBox.information(self, "Customize", "Налаштування успішно застосовано!"))
        layout.addWidget(apply_btn)

        page.setLayout(layout)
        return page

    # 3. Сторінка Plugins (з чітким білим текстом і фіксованими розмірами карток)
    def create_plugins_page(self):
        page = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(40, 30, 40, 20)
        layout.setSpacing(12)

        header = QLabel("<h2>Plugins</h2>")
        header.setStyleSheet("color: #ffffff;")
        layout.addWidget(header)

        search_edit = QLineEdit()
        search_edit.setPlaceholderText("🔍 Search plugins in Marketplace...")
        search_edit.setStyleSheet("background-color: #1e1f22; color: #ffffff; padding: 7px 10px; border: 1px solid #4e5157; border-radius: 4px;")
        layout.addWidget(search_edit)

        plugin_list = QWidget()
        plist_layout = QVBoxLayout()
        plist_layout.setSpacing(8)

        plugins_data = [
            ("🐍 Python Community Edition", "Core Python language support, debugging and virtualenv manager.", "Installed"),
            ("🌈 Rainbow Brackets", "Colorizes matching brackets to ease code reading.", "Install"),
            ("🇺🇦 Ukrainian Language Pack", "Ukrainian language interface and localization.", "Install"),
            ("📊 CSV Plugin", "Table editor and syntax highlighting for CSV/TSV data.", "Install"),
            ("📦 GitToolBox", "Inline git blame, status bar indicators and commit history.", "Install"),
        ]

        for p_name, p_desc, p_status in plugins_data:
            item_frame = QFrame()
            item_frame.setObjectName("pluginCard")
            item_frame.setMinimumHeight(65)
            item_frame.setStyleSheet("""
                QFrame#pluginCard {
                    background-color: #1e1f22;
                    border-radius: 6px;
                    border: 1px solid #393b40;
                }
                QFrame#pluginCard QLabel {
                    background: transparent;
                }
            """)
            item_layout = QHBoxLayout()
            item_layout.setContentsMargins(15, 8, 15, 8)

            info_layout = QVBoxLayout()
            info_layout.setSpacing(2)
            lbl_title = QLabel(f"<b>{p_name}</b>")
            lbl_title.setStyleSheet("color: #ffffff; font-size: 10.5pt;")
            lbl_desc = QLabel(p_desc)
            lbl_desc.setStyleSheet("color: #a0a6b2; font-size: 9pt;")
            lbl_desc.setWordWrap(True)
            info_layout.addWidget(lbl_title)
            info_layout.addWidget(lbl_desc)

            item_layout.addLayout(info_layout)
            item_layout.addStretch()

            btn_status = QPushButton(p_status)
            btn_status.setFixedWidth(95)
            if p_status == "Installed":
                btn_status.setEnabled(False)
                btn_status.setStyleSheet("background-color: #2e3035; color: #6e7279; border: 1px solid #393b40; border-radius: 4px; padding: 6px 10px; font-weight: bold;")
            else:
                btn_status.setStyleSheet("background-color: #3574f0; color: #ffffff; border-radius: 4px; padding: 6px 10px; font-weight: bold; border: none;")
                btn_status.clicked.connect(lambda checked, b=btn_status, n=p_name: self.install_plugin(b, n))

            item_layout.addWidget(btn_status)
            item_frame.setLayout(item_layout)
            plist_layout.addWidget(item_frame)

        plugin_list.setLayout(plist_layout)
        layout.addWidget(plugin_list)
        layout.addStretch()

        page.setLayout(layout)
        return page

    def install_plugin(self, button, plugin_name):
        button.setText("Installed")
        button.setEnabled(False)
        button.setStyleSheet("background-color: #2e3035; color: #6e7279; border: 1px solid #393b40; border-radius: 4px; padding: 6px 10px; font-weight: bold;")
        QMessageBox.information(self, "Plugins", f"Плагін '{plugin_name}' успішно активовано!")

    # 4. Сторінка Learn Python (з чітким білим текстом і кнопками Open)
    def create_learn_page(self):
        page = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(40, 30, 40, 20)
        layout.setSpacing(12)

        header = QLabel("<h2>Learn Python</h2>")
        header.setStyleSheet("color: #ffffff;")
        layout.addWidget(header)

        sub = QLabel("Explore interactive tutorials, shortcuts, and documentation:")
        sub.setStyleSheet("color: #a0a6b2; font-size: 9.5pt;")
        layout.addWidget(sub)

        cards = [
            ("🚀 Start Onboarding Tour", "Learn the basics of the IDE and execution workflow.", lambda: QMessageBox.information(self, "Tour", "Вітаємо в Onboarding Tour!\n1. Виберіть 'New Project'\n2. Пишіть код у редакторі\n3. Тисніть 'Run' ▶ для анімації масивів та блок-схем.")),
            ("📚 Interactive Lessons", "Open built-in Python lessons (Variables, Loops, OOP).", lambda: self.switch_tab(0)),
            ("🌐 Official Python Documentation", "Read comprehensive language documentation and PEP references.", lambda: QMessageBox.information(self, "Docs", "Документація доступна за посиланням: docs.python.org")),
            ("💡 Tip of the Day", "Use Shift+F10 to quickly run code, or Ctrl+Space for autocomplete.", lambda: QMessageBox.information(self, "Порада дня", "Порада:\nУ правому вікні анімацій динамічно відтворюється робота циклів, масивів та дерева спадкування ООП!"))
        ]

        for c_title, c_desc, c_callback in cards:
            c_frame = QFrame()
            c_frame.setObjectName("learnCard")
            c_frame.setMinimumHeight(65)
            c_frame.setStyleSheet("""
                QFrame#learnCard {
                    background-color: #1e1f22;
                    border-radius: 6px;
                    border: 1px solid #393b40;
                }
                QFrame#learnCard QLabel {
                    background: transparent;
                }
            """)
            c_layout = QHBoxLayout()
            c_layout.setContentsMargins(15, 8, 15, 8)

            c_info = QVBoxLayout()
            c_info.setSpacing(2)
            lbl_t = QLabel(f"<b>{c_title}</b>")
            lbl_t.setStyleSheet("color: #ffffff; font-size: 10.5pt;")
            lbl_d = QLabel(c_desc)
            lbl_d.setStyleSheet("color: #a0a6b2; font-size: 9pt;")
            lbl_d.setWordWrap(True)
            c_info.addWidget(lbl_t)
            c_info.addWidget(lbl_d)

            c_layout.addLayout(c_info)
            c_layout.addStretch()

            btn_open = QPushButton("Open")
            btn_open.setFixedWidth(85)
            btn_open.setStyleSheet("background-color: #3574f0; color: #ffffff; border-radius: 4px; padding: 6px 14px; font-weight: bold; border: none;")
            btn_open.clicked.connect(c_callback)
            c_layout.addWidget(btn_open)

            c_frame.setLayout(c_layout)
            layout.addWidget(c_frame)

        layout.addStretch()
        page.setLayout(layout)
        return page

    def on_new_project(self):
        dialog = PyCharmNewProjectDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            project_dir = data["path"]
            if not project_dir:
                return

            try:
                os.makedirs(project_dir, exist_ok=True)

                if data["create_venv"]:
                    venv_dir = os.path.join(project_dir, "venv")
                    scripts_dir = os.path.join(venv_dir, "Scripts" if sys.platform == "win32" else "bin")
                    lib_dir = os.path.join(venv_dir, "Lib", "site-packages") if sys.platform == "win32" else os.path.join(venv_dir, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages")
                    
                    os.makedirs(scripts_dir, exist_ok=True)
                    os.makedirs(lib_dir, exist_ok=True)

                    pyvenv_cfg = os.path.join(venv_dir, "pyvenv.cfg")
                    if not os.path.exists(pyvenv_cfg):
                        with open(pyvenv_cfg, "w", encoding="utf-8") as f:
                            f.write(f"home = {os.path.dirname(sys.executable)}\ninclude-system-site-packages = false\nversion = 3.10\n")

                # Створення чистого main.py БЕЗ будь-якого коду
                if data["create_main"]:
                    main_file_path = os.path.join(project_dir, "main.py")
                    if not os.path.exists(main_file_path):
                        with open(main_file_path, "w", encoding="utf-8") as f:
                            f.write("")

                self.project_selected.emit(project_dir)
                self.close()

            except Exception as e:
                QMessageBox.critical(self, "Помилка", f"Не вдалося створити проєкт:\n{str(e)}")

    def on_open_project(self):
        chosen_dir = QFileDialog.getExistingDirectory(self, "Відкрити існуючий проєкт")
        if chosen_dir:
            self.project_selected.emit(chosen_dir)
            self.close()


# --- Головне вікно додатку ---
class MainWindow(QMainWindow):
    def __init__(self, initial_project_path=None):
        super().__init__()
        self.setWindowTitle("Python Studio")
        self.resize(1600, 1000)

        self.project_path = initial_project_path
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.currentChanged.connect(self.update_title_bar)

        # Налаштування вкладок: щоб усі назви файлів завжди були видимі і не обрізалися
        self.tab_widget.setUsesScrollButtons(True)
        self.tab_widget.setElideMode(Qt.TextElideMode.ElideNone)
        self.tab_widget.setStyleSheet("""
            QTabBar::tab {
                min-width: 110px;
                padding: 6px 14px;
                font-family: 'Consolas', 'Segoe UI';
                font-size: 10pt;
            }
        """)

        self.output = OutputTextEdit()
        self.output.input_submitted.connect(self.handle_direct_user_input)

        self.animation_widget = AdaptiveAnimationWidget()
        self.file_paths = {}
        self.modified_tabs = set()

        self.progress_bar = QProgressBar()
        self.status_bar = QStatusBar()
        self.status_bar.addPermanentWidget(self.progress_bar)
        self.setStatusBar(self.status_bar)

        # Модель файлової системи для дерева проєкту зліва
        self.fs_model = QFileSystemModel()
        self.fs_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)

        self.tree_view = QTreeView()
        self.tree_view.setModel(self.fs_model)
        self.tree_view.doubleClicked.connect(self.open_file_from_tree)
        self.tree_view.setHeaderHidden(True)
        for col in range(1, 4):
            self.tree_view.hideColumn(col)

        self.run_button = QPushButton("▶")
        self.pause_button = QPushButton("⏸")
        self.resume_button = QPushButton("⏯")
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)

        # Панель інструментів (з випадаючим списком файлів .py як у PyCharm)
        toolbar = QToolBar("Головна панель")
        toolbar.addWidget(QLabel(" 🐍 Конфігурація: "))
        self.py_file_selector = QComboBox()
        self.py_file_selector.setMinimumWidth(180)
        self.py_file_selector.setStyleSheet("""
            QComboBox {
                background-color: #ffffff;
                color: #004085;
                font-weight: bold;
                border: 1px solid #cbd5e0;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left: 1px solid #cbd5e0;
            }
        """)
        self.py_file_selector.currentIndexChanged.connect(self.on_py_file_selected)
        toolbar.addWidget(self.py_file_selector)

        toolbar.addSeparator()
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
        file_dock.setMinimumWidth(240)

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

        # Завантаження проєкту
        if self.project_path and os.path.exists(self.project_path):
            self.load_project_folder(self.project_path)
        else:
            self.fs_model.setRootPath(QDir.rootPath())
            self.new_tab(content="", filepath=None)

    def refresh_py_files_dropdown(self):
        """Оновлює випадаючий список файлів .py з поточного проєкту."""
        self.py_file_selector.blockSignals(True)
        self.py_file_selector.clear()

        if self.project_path and os.path.exists(self.project_path):
            py_files = []
            for root, dirs, files in os.walk(self.project_path):
                if "venv" in root or ".git" in root or "__pycache__" in root:
                    continue
                for f in files:
                    if f.endswith(".py"):
                        rel_path = os.path.relpath(os.path.join(root, f), self.project_path)
                        py_files.append((rel_path, os.path.join(root, f)))

            for label, full_path in sorted(py_files):
                self.py_file_selector.addItem(f"📄 {label}", full_path)

        self.py_file_selector.blockSignals(False)

    def on_py_file_selected(self, index):
        full_path = self.py_file_selector.itemData(index)
        if full_path and os.path.exists(full_path):
            for idx in range(self.tab_widget.count()):
                editor = self.tab_widget.widget(idx)
                if self.file_paths.get(editor) == full_path:
                    self.tab_widget.setCurrentIndex(idx)
                    return
            with open(full_path, "r", encoding="utf-8") as f:
                self.new_tab(f.read(), full_path)

    def load_project_folder(self, folder_path):
        self.project_path = folder_path
        root_index = self.fs_model.setRootPath(folder_path)
        self.tree_view.setRootIndex(root_index)
        self.tree_view.expand(root_index)

        self.refresh_py_files_dropdown()

        # Відкриття чистого файлу без стороннього коду
        main_file = os.path.join(folder_path, "main.py")
        if os.path.exists(main_file):
            with open(main_file, "r", encoding="utf-8") as f:
                self.new_tab(f.read(), main_file)
        else:
            self.new_tab(content="", filepath=None)

    def init_menus(self):
        file_menu = self.menuBar().addMenu("📂 Файл")
        
        new_proj_action = QAction("🆕 Створити проєкт...", self)
        new_proj_action.triggered.connect(self.open_new_project_dialog)
        file_menu.addAction(new_proj_action)

        open_proj_action = QAction("📂 Відкрити проєкт...", self)
        open_proj_action.triggered.connect(self.open_project_dialog)
        file_menu.addAction(open_proj_action)
        file_menu.addSeparator()

        file_menu.addAction("📄 Новий файл", self.new_tab)
        file_menu.addAction("📂 Відкрити файл...", self.open_file_dialog)
        file_menu.addAction("💾 Зберегти", self.save_file)
        file_menu.addAction("📝 Зберегти як...", self.save_file_as)
        file_menu.addSeparator()
        
        new_file_action = QAction("➕ Новий файл у проєкті", self)
        new_file_action.triggered.connect(self.create_new_file_in_project)
        file_menu.addAction(new_file_action)

        run_menu = self.menuBar().addMenu("▶ Запуск")
        run_menu.addAction("🚀 Запустити код", self.run_code)

        # Меню навчання
        learning_menu = self.menuBar().addMenu("📚 Навчання")
        learning_menu.addAction("Вступ до Python", lambda: self.show_lesson("intro"))
        learning_menu.addAction("Змінні та типи даних", lambda: self.show_lesson("variables"))
        learning_menu.addAction("Умовні оператори", lambda: self.show_lesson("conditionals"))
        learning_menu.addAction("Цикли", lambda: self.show_lesson("loops"))
        learning_menu.addAction("Функції", lambda: self.show_lesson("functions"))
        learning_menu.addAction("Списки", lambda: self.show_lesson("lists"))
        learning_menu.addAction("Словники", lambda: self.show_lesson("dictionaries"))
        learning_menu.addAction("Обробка винятків", lambda: self.show_lesson("exceptions"))
        learning_menu.addAction("Класи і об'єкти", lambda: self.show_lesson("classes"))
        learning_menu.addAction("Модулі та пакети", lambda: self.show_lesson("modules"))
        learning_menu.addAction("Файли та введення/виведення", lambda: self.show_lesson("files"))
        learning_menu.addSeparator()

    def show_lesson(self, lesson_name):
        lesson_content = self.get_lesson_content(lesson_name)
        QMessageBox.information(self, f"Урок: {lesson_name.capitalize()}", lesson_content)

    def get_lesson_content(self, lesson_name):
        if lesson_name == "intro":
            return """
        Ласкаво просимо до Python!

        Python - це мова програмування високого рівня, яка використовується для розробки веб-сайтів, аналізу даних, штучного інтелекту та багато іншого.
        Вона відома своєю простотою та читабельністю.

        # Приклад коду:
        print("Привіт, світ!")
        """
        elif lesson_name == "variables":
            return """
        Змінні в Python:

        Змінні використовуються для зберігання даних.

        # Приклади:
        name = "Іван"  # Рядок (текст)
        age = 30        # Ціле число
        height = 1.75   # Число з плаваючою комою
        is_student = True # Логічне значення (True або False)

        print(name)
        """
        elif lesson_name == "conditionals":
            return """
        Умовні оператори:

        Використовуються для виконання різних дій в залежності від умови.

        # Приклад:
        age = 20
        if age >= 18:
            print("Ви повнолітній.")
        else:
            print("Ви неповнолітній.")
        """
        elif lesson_name == "loops":
            return """
        Цикли:

        Використовуються для повторення блоку коду кілька разів.

        # Приклад:
        for i in range(5):
            print(i)  # Виведе числа від 0 до 4
        """
        elif lesson_name == "functions":
            return """
        Функції:

        Функції - це блоки коду, які можна повторно використовувати.

        # Приклад:
        def вітання(ім'я):
            print(f"Привіт, {ім'я}!")

        вітання("Петро")
        """
        elif lesson_name == "lists":
            return """
        Списки (arrays) у Python:

        Списки - це впорядковані колекції елементів.  Можуть містити елементи різних типів.
        Масиви (arrays) - аналогічні спискам, але, як правило, містять елементи одного типу і більш ефективні для числових обчислень (потребують імпорту модуля array).

        # Приклади списків:
        my_list = [1, 2, 3, "apple", True] # Список різних типів даних
        numbers = [10, 20, 30, 40, 50]     # Список чисел

        # Доступ до елементів:
        print(my_list[0])  # Виведе 1 (індексація починається з 0)

        # Зміна елементів:
        numbers[2] = 35
        print(numbers)     # Виведе [10, 20, 35, 40, 50]

        # Додавання елементів:
        my_list.append("banana") # Додає елемент в кінець списку
        print(my_list)

        # Вставка елементів:
        my_list.insert(1, "orange") # Вставляє "orange" на позицію 1
        print(my_list)

        # Видалення елементів:
        del my_list[0]       # Видаляє елемент за індексом
        print(my_list)

        my_list.remove("orange") # Видаляє елемент за значенням
        print(my_list)

        #Довжина списку
        print(len(my_list))

        #Приклади масивів:
        import array
        int_array = array.array('i', [1, 2, 3, 4, 5]) # Масив цілих чисел
        print(int_array)

        #Приклад обчислень з масивами (потребує використання бібліотеки NumPy для більш складних операцій)
        import numpy as np
        np_array = np.array([1.0, 2.0, 3.0])
        print(np_array * 2) #Множення на скаляр
        """
        elif lesson_name == "dictionaries":
            return """
        Словники в Python:

        Словники - це невпорядковані колекції пар ключ-значення.  Ключі повинні бути унікальними.

        # Приклади:
        my_dict = {"name": "Іван", "age": 30, "city": "Київ"}

        # Доступ до значень:
        print(my_dict["name"])  # Виведе "Іван"

        # Додавання нових пар:
        my_dict["occupation"] = "Програміст"
        print(my_dict)

        # Зміна значень:
        my_dict["age"] = 31
        print(my_dict)

        # Видалення пар:
        del my_dict["city"]
        print(my_dict)

        #Перевірка наявності ключа
        print("name" in my_dict)

        #Метод get(), щоб отримати значення безпечно
        print(my_dict.get("country", "Країна не вказана")) #Повертає значення, якщо ключ існує, інакше - значення за замовчуванням
        """
        elif lesson_name == "exceptions":
            return """
        Обробка винятків в Python:

        Винятки - це помилки, які виникають під час виконання програми.  Обробка винятків дозволяє "перехопити" помилку і продовжити виконання програми.

        # Приклад:
        try:
            result = 10 / 0  # Це викличе помилку ZeroDivisionError
        except ZeroDivisionError:
            print("Ділення на нуль неможливе!")
        except Exception as e:
            print(f"Виникла інша помилка: {e}")
        finally:
            print("Цей блок коду виконається завжди, незалежно від того, чи була помилка.")
        """
        elif lesson_name == "classes":
            return """
        Класи і об'єкти:

        Класи — це шаблони для створення об'єктів.

        # Приклад класу:
        class Person:
            def __init__(self, name, age):
                self.name = name
                self.age = age

            def greet(self):
                print(f"Привіт, мене звати {self.name}")

        p = Person("Олексій", 25)
        p.greet()
        """
        elif lesson_name == "modules":
            return """
        Модулі та пакети:

        Модулі — це файли з Python кодом, які можна імпортувати.

        # Приклад імпорту:
        import math
        print(math.sqrt(16))  # Виведе 4.0
        """
        elif lesson_name == "files":
            return """
        Файли та введення/виведення:

        Як читати та записувати файли.

        # Приклад запису в файл:
        with open("example.txt", "w") as file:
            file.write("Привіт, файл!")

        # Читання з файлу:
        with open("example.txt", "r") as file:
            content = file.read()
            print(content)
        """
        else:
            return "Урок не знайдено."

    def open_new_project_dialog(self):
        dialog = PyCharmNewProjectDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            project_dir = data["path"]
            if project_dir:
                os.makedirs(project_dir, exist_ok=True)
                if data["create_venv"]:
                    venv_dir = os.path.join(project_dir, "venv")
                    scripts_dir = os.path.join(venv_dir, "Scripts" if sys.platform == "win32" else "bin")
                    lib_dir = os.path.join(venv_dir, "Lib", "site-packages") if sys.platform == "win32" else os.path.join(venv_dir, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages")
                    os.makedirs(scripts_dir, exist_ok=True)
                    os.makedirs(lib_dir, exist_ok=True)
                if data["create_main"]:
                    main_file_path = os.path.join(project_dir, "main.py")
                    if not os.path.exists(main_file_path):
                        with open(main_file_path, "w", encoding="utf-8") as f:
                            f.write("")
                self.load_project_folder(project_dir)

    def open_project_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Відкрити проєкт")
        if folder:
            self.load_project_folder(folder)

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

    def create_new_file_in_project(self):
        if not hasattr(self, 'project_path') or not self.project_path:
            QMessageBox.warning(self, "⚠️ Немає проєкту", "Спочатку створіть або відкрийте проєкт.")
            return

        file_name, ok = QInputDialog.getText(self, "Новий файл", "Введіть назву файлу (.py):")
        if ok and file_name:
            if not file_name.endswith('.py'):
                file_name += '.py'
            file_path = os.path.join(self.project_path, file_name)
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("")
                self.new_tab("", file_path)
                self.refresh_py_files_dropdown()
            except Exception as e:
                QMessageBox.critical(self, "Помилка", str(e))

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

        editor.setFocus()

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
        start_dir = self.project_path if (self.project_path and os.path.exists(self.project_path)) else ""
        path, _ = QFileDialog.getOpenFileName(self, "Відкрити файл", start_dir, "Python (*.py);;All Files (*)")
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self.new_tab(f.read(), path)
                self.refresh_py_files_dropdown()
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
            self.refresh_py_files_dropdown()
        except Exception as e:
            QMessageBox.critical(self, "❌ Помилка", str(e))

    def save_file_as(self):
        editor = self.current_editor()
        if not editor: return
        
        # Гарантоване збереження всередині папки проєкту
        start_dir = self.project_path if (self.project_path and os.path.exists(self.project_path)) else ""
        default_file_path = os.path.join(start_dir, "untitled.py") if start_dir else "untitled.py"
        
        path, _ = QFileDialog.getSaveFileName(self, "Зберегти як", default_file_path, "Python (*.py)")
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(editor.toPlainText())
                self.file_paths[editor] = path
                self.modified_tabs.discard(editor)
                index = self.tab_widget.indexOf(editor)
                self.tab_widget.setTabText(index, os.path.basename(path))
                self.refresh_py_files_dropdown()
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

        if self.tab_widget.count() == 0:
            self.new_tab()

    def run_code(self):
        editor = self.current_editor()
        if not editor:
            return
        code = editor.toPlainText()
        self.output.clear()
        self.output.stop_input_session()
        self.progress_bar.setVisible(True)
        self.run_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.resume_button.setEnabled(False)

        self.runner = CodeRunner(code, project_dir=self.project_path, step_delay=0.45)
        self.runner.output_signal.connect(self.output.append_output)
        self.runner.progress_signal.connect(self.progress_bar.setValue)
        self.runner.finished_signal.connect(self.run_finished)
        self.runner.variable_update_signal.connect(self.animation_widget.update_variables)
        self.runner.input_requested_signal.connect(self.output.start_input_session)
        self.runner.missing_library_signal.connect(self.prompt_install_library)
        self.runner.start()

    def prompt_install_library(self, lib_name: str):
        """Автоматично пропонує завантажити та встановити відсутній модуль у venv проєкту."""
        reply = QMessageBox.question(
            self,
            "📦 Відсутній модуль",
            f"Модуль або бібліотека '{lib_name}' не знайдена у проєкті.\n\nБажаєте автоматично завантажити та встановити '{lib_name}' через pip?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.install_library_via_pip(lib_name)

    def install_library_via_pip(self, lib_name: str):
        self.output.append_output(f"\n⚙️ Початок встановлення бібліотеки '{lib_name}'...\n")
        
        # Визначення інтерпретатора Python у створеному venv
        venv_python = sys.executable
        if self.project_path:
            custom_python = os.path.join(self.project_path, "venv", "Scripts", "python.exe") if sys.platform == "win32" else os.path.join(self.project_path, "venv", "bin", "python")
            if os.path.exists(custom_python):
                venv_python = custom_python

        def run_pip():
            try:
                proc = subprocess.Popen(
                    [venv_python, "-m", "pip", "install", lib_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                stdout, stderr = proc.communicate()
                if proc.returncode == 0:
                    self.output.append_output(f"✅ Бібліотеку '{lib_name}' успішно встановлено!\n\n")
                else:
                    self.output.append_output(f"❌ Помилка встановлення '{lib_name}':\n{stderr}\n")
            except Exception as e:
                self.output.append_output(f"❌ Помилка: {str(e)}\n")

        thread = threading.Thread(target=run_pip)
        thread.daemon = True
        thread.start()

    def handle_direct_user_input(self, user_val: str):
        if hasattr(self, "runner") and self.runner.isRunning():
            self.runner.provide_input(user_val)

    def run_finished(self):
        self.run_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
        self.output.stop_input_session()

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


# --- Точка входу в програму ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Першим відкривається вікно привітання (як у PyCharm)
    welcome_win = PyCharmWelcomeWindow()
    main_win = None

    def start_ide_with_project(project_path):
        global main_win
        main_win = MainWindow(initial_project_path=project_path)
        main_win.show()

    welcome_win.project_selected.connect(start_ide_with_project)
    welcome_win.show()

    sys.exit(app.exec())
