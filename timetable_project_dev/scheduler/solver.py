import subprocess
import os
import tempfile

class TimetableCSPSolver:
    """
    Гібридний солвер: використовує чистий Prolog (SWI-Prolog CLP(FD)) 
    як логічний движок для пошуку розкладу без колізій.
    """
    def __init__(self, week, teachers, subjects, rooms, requirements, unavailabilities):
        self.week = week
        self.teachers = list(teachers)
        self.subjects = list(subjects)
        self.rooms = list(rooms)
        self.requirements = list(requirements)
        self.unavailabilities = list(unavailabilities)

    def solve(self):
        # 1. Формуємо завдання (tasks) для Prolog
        tasks_prolog = []
        task_id = 1
        
        tasks_mapping = []
        for req in self.requirements:
            for i in range(req.hours_per_week):
                # Для кожного заняття створюємо унікальний ідентифікатор
                t_id = f"t{task_id}"
                # Умовно мапимо ID викладача, групи (першої) та аудиторії на числа для Prolog
                t_code = req.teacher.id
                g_code = hash(req.groups) % 1000
                r_code = self.rooms[0].id if self.rooms else 1
                
                tasks_prolog.append(f"task({t_id}, {t_code}, {g_code}, {r_code}, D{task_id}, P{task_id})")
                tasks_mapping.append({
                    'req': req,
                    'day_var': f"D{task_id}",
                    'period_var': f"P{task_id}"
                })
                task_id += 1

        if not tasks_prolog:
            return []

        # 2. Створюємо тимчасовий файл запиту Prolog
        pl_file_path = os.path.abspath("scheduler/timetable.pl")
        
        query_content = f"""
        :- consult('{pl_file_path.replace(os.sep, "/").absolute() if hasattr(pl_file_path, 'absolute') else pl_file_path}').
        
        run_query(ListOfVars) :-
            Tasks = [{', '.join(tasks_prolog)}],
            solve_timetable(Tasks),
            ListOfVars = [{', '.join([f"D{i+1}-P{i+1}" for i in range(len(tasks_mapping))])}].
        """
        
        # Записуємо у тимчасовий файл
        fd, temp_query_path = tempfile.mkstemp(suffix='.pl', text=True)
        os.close(fd)
        with open(temp_query_path, 'w', encoding='utf-8') as f:
            f.write(query_content)

        # 3. Викликаємо SWI-Prolog (swipl) з Python
        days_map = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday"}
        assigned_schedule = []

        try:
            # Виконуємо запит через командний рядок SWI-Prolog
            cmd = ["swipl", "-s", temp_query_path, "-g", "run_query(Res), writeln(Res), halt.", "-t", "halt"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0 or not result.stdout.strip():
                # Якщо Prolog не знайшов рішення або сталася помилка
                os.remove(temp_query_path)
                return None

            output = result.stdout.strip()
            # Приклад виводу від Prolog: [1-3, 2-4, 5-1, ...]
            clean_out = output.strip("[]")
            if not clean_out:
                os.remove(temp_query_path)
                return None

            pairs = clean_out.split(",")
            
            room_counter = 0
            for idx, item_data in enumerate(pairs):
                if "-" not in item_data:
                    continue
                d_str, p_str = item_data.strip().split("-")
                day_num = int(d_str.strip())
                period_num = int(p_str.strip())
                
                day_name = days_map.get(day_num, "Monday")
                mapping_info = tasks_mapping[idx]
                req = mapping_info['req']
                
                # Підбираємо аудиторію
                room = self.rooms[room_counter % len(self.rooms)] if self.rooms else None
                room_counter += 1

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
            print(f"Prolog execution error: {e}")
            assigned_schedule = None
        finally:
            if os.path.exists(temp_query_path):
                os.remove(temp_query_path)

        return assigned_schedule
