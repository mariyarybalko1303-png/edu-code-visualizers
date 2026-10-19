import subprocess
import os
import tempfile

class TimetableCSPSolver:
    """
    Гібридний солвер: використовує чистий Prolog (SWI-Prolog CLP(FD))
    для автоматичного пошуку розкладу без колізій з урахуванням потоків та груп.
    """
    def __init__(self, week, teachers, subjects, rooms, requirements, unavailabilities):
        self.week = week
        self.teachers = list(teachers)
        self.subjects = list(subjects)
        self.rooms = list(rooms)
        self.requirements = list(requirements)
        self.unavailabilities = list(unavailabilities)

    def solve(self):
        tasks_prolog = []
        tasks_mapping = []
        task_id = 1

        # Формуємо список завдань із вимог навантаження
        for req in self.requirements:
            for _ in range(req.hours_per_week):
                t_id = f"t{task_id}"
                t_code = req.teacher.id
                
                # Призначаємо кімнату за замовчуванням або першу вільну
                r_code = self.rooms[(task_id - 1) % len(self.rooms)].id if self.rooms else 1
                
                # Ознака потоку (1 якщо потокове, 0 якщо ні)
                is_stream_val = 1 if req.is_stream else 0
                
                # Список груп у вигляді Prolog-списку, напр: [g1, g2]
                groups_raw = [g.strip().lower() for g in req.groups.split(',') if g.strip()]
                groups_prolog = "[" + ", ".join([f"g_{hash(g) % 10000}" for g in groups_raw]) + "]"

                tasks_prolog.append(f"task({t_id}, {t_code}, {r_code}, {is_stream_val}, D{task_id}, P{task_id}, {groups_prolog})")
                tasks_mapping.append({
                    'req': req,
                    'day_var': f"D{task_id}",
                    'period_var': f"P{task_id}"
                })
                task_id += 1

        if not tasks_prolog:
            return []

        pl_file_path = os.path.abspath("scheduler/timetable.pl")
        
        # Запит до Prolog рушія
        query_content = f"""
        :- consult('{pl_file_path.replace(os.sep, "/") if os.name == 'nt' else pl_file_path}').
        
        run_query(AllVars) :-
            Tasks = [{', '.join(tasks_prolog)}],
            solve_timetable(Tasks, AllVars).
        """

        fd, temp_query_path = tempfile.mkstemp(suffix='.pl', text=True)
        os.close(fd)
        with open(temp_query_path, 'w', encoding='utf-8') as f:
            f.write(query_content)

        days_map = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday"}
        assigned_schedule = []

        try:
            # Запускаємо SWI-Prolog (swipl)
            cmd = ["swipl", "-s", temp_query_path, "-g", "run_query(Vars), writeln(Vars), halt.", "-t", "halt"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

            if result.returncode != 0 or not result.stdout.strip():
                if os.path.exists(temp_query_path):
                    os.remove(temp_query_path)
                return None  # Prolog не знайшов розв'язку без колізій

            output = result.stdout.strip().strip("[]")
            if not output:
                if os.path.exists(temp_query_path):
                    os.remove(temp_query_path)
                return None

            # Розбираємо змінні, знайдені Prolog [D1, D2, ..., P1, P2, ...]
            raw_vals = [int(v.strip()) for v in output.split(",") if v.strip().isdigit()]
            
            num_tasks = len(tasks_mapping)
            days_vals = raw_vals[:num_tasks]
            periods_vals = raw_vals[num_tasks:num_tasks * 2]

            room_idx = 0
            for idx, mapping in enumerate(tasks_mapping):
                req = mapping['req']
                day_num = days_vals[idx] if idx < len(days_vals) else 1
                period_num = periods_vals[idx] if idx < len(periods_vals) else 1

                day_name = days_map.get(day_num, "Monday")
                room = self.rooms[room_idx % len(self.rooms)] if self.rooms else None
                room_idx += 1

                assigned_schedule.append({
                    'week': self.week,
                    'day': day_name,
                    'period': period_num,
                    'teacher': req.teacher,
                    'subject': req.subject,
                    'room': room,
                    'groups': req.groups,
                    'is_stream': req.is_stream
                })

        except Exception as e:
            print(f"Prolog Execution Error: {e}")
            assigned_schedule = None
        finally:
            if os.path.exists(temp_query_path):
                os.remove(temp_query_path)

        return assigned_schedule
