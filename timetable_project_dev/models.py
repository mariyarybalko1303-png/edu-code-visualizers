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

class ScheduleItem(models.Model):
    WEEK_CHOICES = [
        (1, "1-й тиждень (Чисельник)"),
        (2, "2-й тиждень (Знаменник)"),
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
    group_name = models.CharField("Група", max_length=50, default="314-і")

    class Meta:
        unique_together = ('week', 'day', 'period', 'teacher')

    def __str__(self):
        return f"Тиждень {self.week} | {self.day} | {self.period} пара: {self.subject} ({self.teacher})"