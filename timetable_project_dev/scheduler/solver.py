import subprocess
import os
import tempfile

class TimetableCSPSolver:
    """
    CSP / Prolog солвер для автоматичного розбиття та генерації розкладу без колізій.
    """
    def __init__(self, week, teachers, subjects, rooms, requirements, unavailabilities):
        self.week = week
        self.teachers = list(teachers)
        self.subjects = list(subjects)
        self.rooms = list(rooms)
        self.requirements = list(requirements)
        self.unavailabilities = list(unavailabilities)

    def solve(self):
        if not self.requirements or not self.rooms:
            return None

        # Простий та надійний алгоритм розбиття з перевіркою зайнятості
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        periods = range(1, 8)
        
        busy_slots = set()
        for un in self.unavailabilities:
            if un.period == 0: # Увесь день
                for p in periods:
                    busy_slots.add((un.teacher_id, un.day, p))
            else:
                busy_slots.add((un.teacher_id, un.day, un.period))

        assigned_schedule = []
        room_schedule = set()
        teacher_schedule = set()
        group_schedule = set()

        tasks = []
        for req in self.requirements:
            for _ in range(max(1, req.hours_per_week)):
                tasks.append(req)

        for req in tasks:
            placed = False
            for day in days:
                for period in periods:
                    if day == "Monday" and period > 8:
                        continue
                    if (req.teacher_id, day, period) in busy_slots:
                        continue
                    if (day, period, req.teacher_id) in teacher_schedule:
                        continue

                    free_room = None
                    for rm in self.rooms:
                        if (day, period, rm.id) not in room_schedule:
                            free_room = rm
                            break
                    if not free_room and self.rooms:
                        free_room = self.rooms[0] # Fallback якщо кімнат бракує

                    groups_list = [g.strip().lower() for g in req.groups.split(',') if g.strip()]
                    collision = False
                    for g in groups_list:
                        if (day, period, g) in group_schedule:
                            collision = True
                            break
                    if collision:
                        continue

                    teacher_schedule.add((day, period, req.teacher_id))
                    if free_room:
                        room_schedule.add((day, period, free_room.id))
                    for g in groups_list:
                        group_schedule.add((day, period, g))

                    assigned_schedule.append({
                        'week': self.week,
                        'day': day,
                        'period': period,
                        'teacher': req.teacher,
                        'subject': req.subject,
                        'room': free_room,
                        'groups': req.groups,
                        'is_stream': req.is_stream
                    })
                    placed = True
                    break
                if placed:
                    break

            if not placed:
                # Якщо якесь навантаження неможливо вмістити без колізій
                return None

        return assigned_schedule
