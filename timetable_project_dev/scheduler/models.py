from django.db import models

class Teacher(models.Model):
    name = models.CharField(max_length=150, verbose_name="ПІБ викладача")
    department = models.CharField(max_length=150, blank=True, default="", verbose_name="Кафедра")

    def __str__(self):
        return self.name

class Student(models.Model):
    full_name = models.CharField(max_length=150, verbose_name="ПІБ студента")
    faculty = models.CharField(max_length=150, verbose_name="Факультет")
    course = models.PositiveSmallIntegerField(default=1, verbose_name="Курс")
    group_name = models.CharField(max_length=50, verbose_name="Група")

    def __str__(self):
        return f"{self.full_name} ({self.group_name})"

class Subject(models.Model):
    title = models.CharField(max_length=150, verbose_name="Назва дисципліни")

    def __str__(self):
        return self.title

class Room(models.Model):
    number = models.CharField(max_length=50, verbose_name="Номер аудиторії")

    def __str__(self):
        return self.number

class TeacherUnavailability(models.Model):
    DAY_CHOICES = [
        ("Monday", "Понеділок"),
        ("Tuesday", "Вівторок"),
        ("Wednesday", "Середа"),
        ("Thursday", "Четвер"),
        ("Friday", "П'ятниця"),
    ]
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="unavailabilities")
    day = models.CharField(max_length=10, choices=DAY_CHOICES)
    period = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return f"{self.teacher.name} - {self.get_day_display()} ({self.period} пара)"

class LessonRequirement(models.Model):
    week = models.PositiveSmallIntegerField(default=1)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    groups = models.CharField(max_length=200)
    is_stream = models.BooleanField(default=False)
    hours_per_week = models.PositiveSmallIntegerField(default=1)

class ScheduleItem(models.Model):
    DAY_CHOICES = TeacherUnavailability.DAY_CHOICES
    week = models.PositiveSmallIntegerField(default=1)
    day = models.CharField(max_length=10, choices=DAY_CHOICES)
    period = models.PositiveSmallIntegerField()
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True)
    groups = models.CharField(max_length=200, blank=True, default="")
    is_stream = models.BooleanField(default=False)

    class Meta:
        unique_together = ('week', 'day', 'period', 'room')
