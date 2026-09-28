from django.db import models

class Teacher(models.Model):
    name = models.CharField("ПІБ викладача", max_length=150)
    department = models.CharField("Кафедра", max_length=100, blank=True, default="ІПЗ / КН")

    def __str__(self):
        return self.name

class Subject(models.Model):
    title = models.CharField("Назва дисципліни", max_length=200)

    def __str__(self):
        return self.title

class Room(models.Model):
    number = models.CharField("Номер аудиторії", max_length=20, unique=True)
    capacity = models.PositiveIntegerField("Місткість", default=30)

    def __str__(self):
        return f"ауд. {self.number}"

class TeacherUnavailability(models.Model):
    """Обмеження зайнятості викладача"""
    DAY_CHOICES = [
        ("Monday", "Понеділок"),
        ("Tuesday", "Вівторок"),
        ("Wednesday", "Середа"),
        ("Thursday", "Четвер"),
        ("Friday", "П'ятниця"),
    ]
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="unavailabilities")
    day = models.CharField("День", max_length=20, choices=DAY_CHOICES)
    period = models.PositiveSmallIntegerField("Пара (0 = увесь день)", default=0)

    def __str__(self):
        p_str = "увесь день" if self.period == 0 else f"{self.period} пара"
        return f"{self.teacher.name} — {self.get_day_display()} ({p_str})"

class LessonRequirement(models.Model):
    """Вимоги навантаження для автогенератора"""
    week = models.PositiveSmallIntegerField("Тиждень", choices=[(1, "1 тиждень"), (2, "2 тиждень")], default=1)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    groups = models.CharField("Групи через кому", max_length=150, default="314-і", help_text="Напр.: 314-і, 315-і")
    is_stream = models.BooleanField("Потокова лекція", default=False)
    hours_per_week = models.PositiveSmallIntegerField("Кількість пар", default=1)

    def get_group_list(self):
        return [g.strip() for g in self.groups.split(',') if g.strip()]

    def __str__(self):
        stream_tag = " [ПОТОКОВА]" if self.is_stream else ""
        return f"{self.subject} - {self.teacher} ({self.groups}){stream_tag} [{self.hours_per_week} пар]"

class ScheduleItem(models.Model):
    WEEK_CHOICES = [
        (1, "1 тиждень"),
        (2, "2 тиждень"),
    ]
    DAY_CHOICES = [
        ("Monday", "Понеділок"),
        ("Tuesday", "Вівторок"),
        ("Wednesday", "Середа"),
        ("Thursday", "Четвер"),
        ("Friday", "П'ятниця"),
    ]

    week = models.PositiveSmallIntegerField("Тиждень", choices=WEEK_CHOICES, default=1)
    day = models.CharField("День тижня", max_length=20, choices=DAY_CHOICES)
    period = models.PositiveSmallIntegerField("Номер пари")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, verbose_name="Викладач")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="Дисципліна")
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Аудиторія")
    groups = models.CharField("Групи", max_length=150, default="314-і")
    is_stream = models.BooleanField("Потокова лекція", default=False)

    class Meta:
        # Жорсткі обмеження від колізій
        unique_together = [
            ('week', 'day', 'period', 'teacher'),
            ('week', 'day', 'period', 'room'),
        ]

    def get_group_list(self):
        return [g.strip() for g in self.groups.split(',') if g.strip()]

    def __str__(self):
        room_str = f" ({self.room})" if self.room else ""
        return f"{self.week} тиждень | {self.day} | {self.period} пара: {self.subject} [{self.teacher}]{room_str}"
