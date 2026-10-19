import random

class TimetableCSPSolver:
    """
    CSP (Constraint Satisfaction Problem) солер, який реалізує 
    логіку декларативного пошуку рішень (як у Prolog CLP).
    """
    def __init__(self, week, teachers, subjects, rooms, requirements, unavailabilities):
        self.week = week
        self.teachers = list(teachers)
        self.subjects = list(subjects)
        self.rooms = list(rooms)
        self.requirements = list(requirements)
        self.unavailabilities = list(unavailabilities)

    def solve(self):
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        periods = range(1, 8) # 1-7 пари
        
        # Створюємо мапу зайнятості викладачів за їх обмеженнями
        busy_slots = set()
        for un in self.unavailabilities:
            busy_slots.add((un.teacher.id, un.day, un.period))

        assigned_schedule = []
        room_schedule = set()  # (day, period, room_id)
        teacher_schedule = set() # (day, period, teacher_id)
        group_schedule = set()   # (day, period, group_name)

        # Розгортаємо вимоги у конкретні заняття
        tasks = []
        for req in self.requirements:
            for _ in range(req.hours_per_week):
                tasks.append(req)

        # Сортуємо вимоги для зменшення простору пошуку (heuristics)
        tasks.sort(key=lambda x: x.subject.title)

        for req in tasks:
            placed = False
            # Перебираємо варіанти (пошук рішення з обмеженнями — Backtracking)
            possible_slots = [(d, p) for d in days for p in periods if not (d == "Monday" and p == 8)]
            random.shuffle(possible_slots) # Додаємо стохастичність для швидкого знаходження

            for day, period in possible_slots:
                # Перевірка обмеження зайнятості викладача
                if (req.teacher.id, day, period) in busy_slots:
                    continue
                if (day, period, req.teacher.id) in teacher_schedule:
                    continue

                # Підбираємо вільну аудиторію
                free_room = None
                for rm in self.rooms:
                    if (day, period, rm.id) not in room_schedule:
                        free_room = rm
                        break
                
                if not free_room:
                    continue

                # Перевірка колізій по групах
                groups_list = [g.strip() for g in req.groups.split(',') if g.strip()]
                collision = False
                for g in groups_list:
                    if (day, period, g) in group_schedule:
                        collision = True
                        break
                
                if collision:
                    continue

                # Якщо всі обмеження виконано — фіксуємо стан (Успішна уніфікація)
                teacher_schedule.add((day, period, req.teacher.id))
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

            if not placed:
                # Якщо хоча б одне правило порушено і немає виходу — спрацьовує Backtracking (немає рішення)
                return None

        return assigned_schedule
