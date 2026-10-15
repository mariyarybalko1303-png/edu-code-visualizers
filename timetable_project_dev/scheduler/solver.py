import random
from typing import List, Dict, Optional

class TimetableCSPSolver:
    def __init__(self, week: int, teachers, subjects, rooms, requirements, unavailabilities):
        self.week = week
        self.teachers = teachers
        self.subjects = subjects
        self.rooms = rooms
        self.requirements = requirements
        self.unavailabilities = unavailabilities

        # Структура слотів: Понеділок (1..7), інші дні (1..8)
        self.slots = []
        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
            max_p = 7 if day == "Monday" else 8
            for p in range(1, max_p + 1):
                self.slots.append((day, p))

    def solve(self) -> Optional[List[Dict]]:
        lessons_to_place = []
        for req in self.requirements:
            for _ in range(req.hours_per_week):
                lessons_to_place.append({
                    'req_id': req.id,
                    'subject': req.subject,
                    'teacher': req.teacher,
                    'groups': req.get_group_list(),
                    'is_stream': req.is_stream,
                    'groups_str': req.groups
                })

        # Сортуємо: спершу потокові лекції (вони мають більше обмежень)
        lessons_to_place.sort(key=lambda x: (not x['is_stream'], len(x['groups'])), reverse=True)

        assignment = []
        if self._backtrack(lessons_to_place, 0, assignment):
            return assignment
        return None

    def _backtrack(self, lessons: List[Dict], lesson_idx: int, assignment: List[Dict]) -> bool:
        if lesson_idx == len(lessons):
            return True

        current_lesson = lessons[lesson_idx]

        for day, period in self.slots:
            for room in self.rooms:
                if self._is_valid(current_lesson, day, period, room, assignment):
                    entry = {
                        'week': self.week,
                        'day': day,
                        'period': period,
                        'teacher': current_lesson['teacher'],
                        'subject': current_lesson['subject'],
                        'groups': current_lesson['groups_str'],
                        'is_stream': current_lesson['is_stream'],
                        'room': room
                    }
                    assignment.append(entry)

                    if self._backtrack(lessons, lesson_idx + 1, assignment):
                        return True

                    assignment.pop()

        return False

    def _is_valid(self, lesson: Dict, day: str, period: int, room, assignment: List[Dict]) -> bool:
        # 1. Понеділок максимум 7 пар
        if day == "Monday" and period > 7:
            return False

        # 2. Перевірка недоступності викладача
        for un in self.unavailabilities:
            if un.teacher_id == lesson['teacher'].id and un.day == day:
                if un.period == 0 or un.period == period:
                    return False

        # 3. Перевірка колізій із уже призначеними парами
        current_groups_set = set(lesson['groups'])

        for assigned in assignment:
            if assigned['day'] == day and assigned['period'] == period:
                # Один викладач на двох парах
                if assigned['teacher'].id == lesson['teacher'].id:
                    return False

                # Аудиторія зайнята
                if assigned['room'].id == room.id:
                    return False

                # Перетин хоча б однієї академічної групи (включаючи потоки)
                assigned_groups_set = set(g.strip() for g in assigned['groups'].split(',') if g.strip())
                if current_groups_set.intersection(assigned_groups_set):
                    return False

        return True
